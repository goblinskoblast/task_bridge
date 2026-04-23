from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from db.database import get_db_session
from db.models import DataAgentSystem, PointStatRun, PointStatSnapshot, SavedPoint, User

from .blanks_tool import blanks_tool
from .italian_pizza import resolve_italian_pizza_point
from .monitoring import MONITOR_USER_TIMEZONE
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)
USER_TIMEZONE = ZoneInfo(MONITOR_USER_TIMEZONE)


class PointStatisticsService:
    async def collect_due_points(self) -> dict:
        db = get_db_session()
        try:
            due_points = self._load_due_points(db)
            if not due_points:
                return {"status": "idle", "runs": 0, "snapshots": 0}

            grouped: dict[int, list[SavedPoint]] = defaultdict(list)
            for point in due_points:
                grouped[point.user_id].append(point)

            run_count = 0
            snapshot_count = 0
            for user_id, points in grouped.items():
                created = await self._collect_for_user(db, user_id, points)
                if created:
                    run_count += 1
                    snapshot_count += created

            return {"status": "ok", "runs": run_count, "snapshots": snapshot_count}
        finally:
            db.close()

    def _load_due_points(self, db: Session) -> list[SavedPoint]:
        now = datetime.utcnow()
        active_points = (
            db.query(SavedPoint)
            .filter(SavedPoint.is_active.is_(True))
            .order_by(SavedPoint.user_id.asc(), SavedPoint.id.asc())
            .all()
        )

        due: list[SavedPoint] = []
        for point in active_points:
            interval = max(int(point.stats_interval_minutes or 240), 1)
            if not point.last_stats_collected_at:
                due.append(point)
                continue
            if point.last_stats_collected_at <= now - timedelta(minutes=interval):
                due.append(point)
        return due

    async def _collect_for_user(self, db: Session, user_id: int, points: list[SavedPoint]) -> int:
        run = PointStatRun(user_id=user_id, status="running", run_started_at=datetime.utcnow())
        db.add(run)
        db.commit()
        db.refresh(run)

        snapshots_created = 0
        had_errors = False
        try:
            for point in points:
                snapshot = await self._collect_point_snapshot(db, run, point)
                if snapshot.source_error:
                    had_errors = True
                snapshots_created += 1

            run.status = "completed_with_errors" if had_errors else "completed"
            run.run_finished_at = datetime.utcnow()
            db.commit()
            return snapshots_created
        except Exception as exc:
            db.rollback()
            logger.error("Point statistics run failed user_id=%s error=%s", user_id, exc, exc_info=True)
            run.status = "failed"
            run.error_text = str(exc)
            run.run_finished_at = datetime.utcnow()
            db.add(run)
            db.commit()
            return snapshots_created

    async def _collect_point_snapshot(self, db: Session, run: PointStatRun, point: SavedPoint) -> PointStatSnapshot:
        stoplist_result = await stoplist_tool.collect_for_point(
            url="",
            username="",
            encrypted_password="",
            point_name=point.display_name,
        )
        stoplist_items = self._extract_stoplist_items(stoplist_result)
        source_errors: list[str] = []
        if (stoplist_result.get("status") or "").lower() not in {"ok", "completed"}:
            source_errors.append(
                str(stoplist_result.get("message") or stoplist_result.get("report_text") or "stoplist_failed")
            )

        blanks_total_count = 0
        blanks_red_count = 0
        blanks_items: list[str] = []
        system = self._resolve_system_for_point(db, point)
        if system:
            blanks_result = await blanks_tool.inspect_point(
                url=system.url,
                username=system.login,
                encrypted_password=system.encrypted_password,
                point_name=point.display_name,
                period_hint="предыдущие 12 часов",
            )
            diagnostics = blanks_result.get("diagnostics") or {}
            blanks_total_count = int(diagnostics.get("slot_count") or diagnostics.get("table_count") or 0)
            blanks_red_count = int(diagnostics.get("red_signal_count") or 0)
            blanks_items = self._extract_blanks_items(blanks_result)
            if (blanks_result.get("status") or "").lower() not in {"ok", "completed"}:
                source_errors.append(
                    str(blanks_result.get("message") or blanks_result.get("report_text") or "blanks_failed")
                )
        else:
            source_errors.append("italian_pizza_system_not_connected")

        snapshot = PointStatSnapshot(
            run_id=run.id,
            saved_point_id=point.id,
            snapshot_at=datetime.utcnow(),
            stoplist_count=len(stoplist_items),
            stoplist_items_json=stoplist_items,
            blanks_total_count=blanks_total_count,
            blanks_red_count=blanks_red_count,
            blanks_overload_items_json=blanks_items,
            source_ok=not source_errors,
            source_error="; ".join(source_errors) if source_errors else None,
        )
        db.add(snapshot)
        point.last_stats_collected_at = snapshot.snapshot_at
        db.commit()
        db.refresh(snapshot)
        logger.info(
            "Point statistics snapshot saved user_id=%s point=%s stoplist=%s blanks_red=%s source_ok=%s",
            run.user_id,
            point.display_name,
            snapshot.stoplist_count,
            snapshot.blanks_red_count,
            snapshot.source_ok,
        )
        return snapshot

    def enrich_stoplist_report(self, user_id: int, point_name: str, result: dict) -> dict:
        status = str(result.get("status") or "").lower()
        if status not in {"ok", "completed"}:
            return result

        current_items = self._extract_stoplist_items(result)
        enriched = dict(result)
        enriched["items"] = current_items

        db = get_db_session()
        try:
            point = self._find_saved_point_by_name(db, user_id, point_name)
            if not point:
                enriched["delta"] = {"added": current_items, "removed": [], "stayed": []}
                enriched["report_text"] = self._render_stoplist_report(
                    point_name=point_name,
                    current_items=current_items,
                    delta=enriched["delta"],
                    has_history=False,
                    is_saved_point=False,
                )
                return enriched

            snapshots = self._list_snapshots(db, point.id)
            previous_snapshot = snapshots[-1] if snapshots else None
            previous_items = self._normalize_items(previous_snapshot.stoplist_items_json if previous_snapshot else [])
            delta = self._compute_stoplist_delta(previous_items, current_items)
            history_days = self._build_stoplist_item_history_days(snapshots, current_items)

            enriched["delta"] = delta
            enriched["stoplist_age_days"] = history_days["current"]
            enriched["removed_stoplist_age_days"] = history_days["removed"]
            enriched["report_text"] = self._render_stoplist_report(
                point_name=point.display_name,
                current_items=current_items,
                delta=delta,
                has_history=previous_snapshot is not None,
                is_saved_point=True,
                current_age_days=history_days["current"],
                removed_age_days=history_days["removed"],
            )

            self._store_stoplist_snapshot(db, point, current_items)
            return enriched
        except Exception as exc:
            logger.error(
                "Stoplist history enrich failed user_id=%s point=%s error=%s",
                user_id,
                point_name,
                exc,
                exc_info=True,
            )
            enriched["report_text"] = self._render_stoplist_report(
                point_name=point_name,
                current_items=current_items,
                delta={"added": current_items, "removed": [], "stayed": []},
                has_history=False,
                is_saved_point=False,
            )
            return enriched
        finally:
            db.close()

    def _find_italian_pizza_system(self, db: Session, user_id: int) -> DataAgentSystem | None:
        return (
            db.query(DataAgentSystem)
            .filter(
                DataAgentSystem.user_id == user_id,
                DataAgentSystem.is_active.is_(True),
                (DataAgentSystem.system_name == "italian_pizza") | (DataAgentSystem.url.contains("italianpizza")),
            )
            .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
            .first()
        )

    def _resolve_system_for_point(self, db: Session, point: SavedPoint) -> DataAgentSystem | None:
        if point.system_id:
            system = (
                db.query(DataAgentSystem)
                .filter(
                    DataAgentSystem.id == point.system_id,
                    DataAgentSystem.user_id == point.user_id,
                    DataAgentSystem.is_active.is_(True),
                )
                .first()
            )
            if system:
                return system
        return self._find_italian_pizza_system(db, point.user_id)

    def _extract_stoplist_items(self, result: dict) -> list[str]:
        explicit_items = result.get("items")
        if isinstance(explicit_items, list):
            normalized = self._normalize_items(explicit_items)
            if normalized:
                return normalized

        report_text = str(result.get("report_text") or "")
        items: list[str] = []
        for line in report_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("• "):
                item = stripped[2:].strip()
                if item and item not in items:
                    items.append(item)
        return items

    def _extract_blanks_items(self, result: dict) -> list[str]:
        diagnostics = result.get("diagnostics") or {}
        values: list[str] = []
        for key in ("styled_cell_samples", "table_samples", "inspected_slots"):
            data = diagnostics.get(key) or []
            if isinstance(data, list):
                for item in data:
                    normalized = str(item).strip()
                    if normalized and normalized not in values:
                        values.append(normalized)
        return values[:30]

    def _find_saved_point_by_name(self, db: Session, telegram_user_id: int, point_name: str) -> SavedPoint | None:
        user = db.query(User).filter(User.telegram_id == telegram_user_id).first()
        if not user:
            return None

        points = (
            db.query(SavedPoint)
            .filter(
                SavedPoint.user_id == user.id,
                SavedPoint.is_active.is_(True),
                SavedPoint.provider == "italian_pizza",
            )
            .all()
        )
        if not points:
            return None

        resolved_target = resolve_italian_pizza_point(point_name)
        target_slug = resolved_target.public_slug if resolved_target else None
        target_city = self._normalize_text(resolved_target.city if resolved_target else "")
        target_address = self._normalize_text(resolved_target.address if resolved_target else "")
        normalized_target_display = self._normalize_point_name(point_name)

        for point in points:
            if self._matches_saved_point(
                point,
                target_slug=target_slug,
                target_city=target_city,
                target_address=target_address,
                normalized_target_display=normalized_target_display,
            ):
                return point
        return None

    def _get_latest_snapshot(self, db: Session, saved_point_id: int) -> PointStatSnapshot | None:
        return (
            db.query(PointStatSnapshot)
            .filter(PointStatSnapshot.saved_point_id == saved_point_id)
            .order_by(PointStatSnapshot.snapshot_at.desc(), PointStatSnapshot.id.desc())
            .first()
        )

    def _list_snapshots(self, db: Session, saved_point_id: int) -> list[PointStatSnapshot]:
        return (
            db.query(PointStatSnapshot)
            .filter(PointStatSnapshot.saved_point_id == saved_point_id)
            .order_by(PointStatSnapshot.snapshot_at.asc(), PointStatSnapshot.id.asc())
            .all()
        )

    def _build_stoplist_item_history_days(
        self,
        snapshots: list[PointStatSnapshot],
        current_items: list[str],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, dict[str, int]]:
        if not snapshots:
            return {
                "current": {item: 1 for item in current_items},
                "removed": {},
            }

        ongoing_start_by_item: dict[str, datetime] = {}
        previous_items: set[str] = set()
        previous_snapshot_at: datetime | None = None

        for snapshot in snapshots:
            snapshot_at = snapshot.snapshot_at
            snapshot_items = set(self._normalize_items(snapshot.stoplist_items_json))
            if previous_items and self._should_reset_stoplist_history(previous_items, snapshot_items):
                ongoing_start_by_item.clear()
                previous_items = set()
            ended_items = previous_items - snapshot_items
            for item in ended_items:
                ongoing_start_by_item.pop(item, None)
            for item in snapshot_items:
                ongoing_start_by_item.setdefault(item, snapshot_at)
            previous_items = snapshot_items
            previous_snapshot_at = snapshot_at

        current_set = set(current_items)
        current_days: dict[str, int] = {}
        current_reference = as_of or datetime.utcnow()
        last_snapshot_at = previous_snapshot_at or current_reference

        if previous_items and self._should_reset_stoplist_history(previous_items, current_set):
            return {
                "current": {item: 1 for item in current_items},
                "removed": {item: 1 for item in previous_items - current_set},
            }

        for item in current_items:
            if item in previous_items:
                start_at = ongoing_start_by_item.get(item, last_snapshot_at)
                current_days[item] = self._count_user_facing_days(start_at, current_reference)
            else:
                current_days[item] = 1

        removed_days: dict[str, int] = {}
        for item in previous_items - current_set:
            start_at = ongoing_start_by_item.get(item, last_snapshot_at)
            removed_days[item] = self._count_user_facing_days(start_at, last_snapshot_at)

        return {
            "current": current_days,
            "removed": removed_days,
        }

    def _should_reset_stoplist_history(self, previous_items: set[str], current_items: set[str]) -> bool:
        if not previous_items or not current_items:
            return False

        changed_count = len(previous_items.symmetric_difference(current_items))
        baseline = max(len(previous_items), len(current_items))
        if changed_count < 6 or baseline < 6:
            return False

        return (changed_count / baseline) >= 0.35

    def _store_stoplist_snapshot(self, db: Session, point: SavedPoint, current_items: list[str]) -> None:
        now = datetime.utcnow()
        run = PointStatRun(
            user_id=point.user_id,
            status="completed",
            run_started_at=now,
            run_finished_at=now,
        )
        db.add(run)
        db.flush()

        snapshot = PointStatSnapshot(
            run_id=run.id,
            saved_point_id=point.id,
            snapshot_at=now,
            stoplist_count=len(current_items),
            stoplist_items_json=current_items,
            blanks_total_count=0,
            blanks_red_count=0,
            blanks_overload_items_json=[],
            source_ok=True,
            source_error=None,
        )
        db.add(snapshot)
        point.last_stats_collected_at = now
        db.commit()

    def _normalize_point_name(self, value: str) -> str:
        resolved = resolve_italian_pizza_point(value or "")
        if resolved:
            return self._normalize_text(f"{resolved.city} {resolved.address}")
        return self._normalize_text(value)

    def _matches_saved_point(
        self,
        point: SavedPoint,
        *,
        target_slug: str | None,
        target_city: str,
        target_address: str,
        normalized_target_display: str,
    ) -> bool:
        if target_slug and point.external_point_key == target_slug:
            return True
        if target_city and target_address:
            if self._normalize_text(point.city) == target_city and self._normalize_text(point.address) == target_address:
                return True
        return self._normalize_point_name(point.display_name) == normalized_target_display

    def _normalize_text(self, value: str) -> str:
        normalized = (value or "").lower().replace("ё", "е")
        normalized = normalized.replace("ул.", " ").replace("улица", " ").replace("тц", " ")
        normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _normalize_items(self, items: list[str] | tuple[str, ...] | None) -> list[str]:
        normalized: list[str] = []
        for item in items or []:
            cleaned = re.sub(r"\s+", " ", str(item or "").strip())
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _compute_stoplist_delta(self, previous_items: list[str], current_items: list[str]) -> dict[str, list[str]]:
        current_set = set(current_items)
        previous_set = set(previous_items)
        return {
            "added": [item for item in current_items if item not in previous_set],
            "removed": [item for item in previous_items if item not in current_set],
            "stayed": [item for item in current_items if item in previous_set],
        }

    def _count_user_facing_days(self, started_at: datetime, finished_at: datetime) -> int:
        if started_at.tzinfo is None:
            started_local = started_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(USER_TIMEZONE)
        else:
            started_local = started_at.astimezone(USER_TIMEZONE)
        if finished_at.tzinfo is None:
            finished_local = finished_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(USER_TIMEZONE)
        else:
            finished_local = finished_at.astimezone(USER_TIMEZONE)
        return max((finished_local.date() - started_local.date()).days + 1, 1)

    def _format_days_label(self, days: int) -> str:
        value = max(int(days or 1), 1)
        remainder_10 = value % 10
        remainder_100 = value % 100
        if remainder_10 == 1 and remainder_100 != 11:
            suffix = "день"
        elif remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
            suffix = "дня"
        else:
            suffix = "дней"
        return f"{value} {suffix}"

    def _stoplist_age_marker(self, days: int | None, *, removed: bool = False) -> str:
        if removed or not days:
            return ""
        return "🟡" if days <= 3 else "🔴"

    def _render_stoplist_section(
        self,
        title: str,
        items: list[str],
        *,
        age_days: dict[str, int] | None = None,
        removed: bool = False,
    ) -> list[str]:
        lines = [f"{title}: {len(items)}"]
        age_days = age_days or {}
        for index, item in enumerate(items, start=1):
            days = age_days.get(item)
            marker = self._stoplist_age_marker(days, removed=removed)
            line = f"{index}. {marker} {item}" if marker else f"{index}. {item}"
            if days:
                line += f" — {'была в стопе' if removed else 'в стопе'} {self._format_days_label(days)}"
            lines.append(line)
        return lines

    def _render_stoplist_report(
        self,
        point_name: str,
        current_items: list[str],
        delta: dict[str, list[str]],
        *,
        has_history: bool,
        is_saved_point: bool,
        current_age_days: dict[str, int] | None = None,
        removed_age_days: dict[str, int] | None = None,
    ) -> str:
        lines = [f"📍 Точка: {point_name}"]
        current_age_days = current_age_days or {}
        removed_age_days = removed_age_days or {}

        if current_items:
            lines.append(f"🚫 Сейчас в стоп-листе: {len(current_items)}")
        else:
            lines.append("✅ Сейчас в стоп-листе недоступных позиций нет.")

        lines.append("")
        if current_items:
            if has_history and is_saved_point:
                if delta["added"]:
                    lines.extend(
                        self._render_stoplist_section(
                            "🆕 Новые в стопе",
                            delta["added"],
                            age_days=current_age_days,
                        )
                    )
                    lines.append("")
                if delta["stayed"]:
                    lines.extend(
                        self._render_stoplist_section(
                            "🟠 Уже в стопе",
                            delta["stayed"],
                            age_days=current_age_days,
                        )
                    )
                    lines.append("")
            else:
                lines.extend(self._render_stoplist_section("🟠 Сейчас в стопе", current_items))
                lines.append("")

        if not is_saved_point:
            lines.append("ℹ️ Чтобы видеть новые позиции, ушедшие позиции и дни в стопе, сохраните эту точку в боте.")
            return "\n".join(lines)

        if not has_history:
            lines.append("🕓 Разделю позиции на новые и ушедшие и покажу дни в стопе после следующей проверки этой точки.")
            return "\n".join(lines)

        if delta["removed"]:
            lines.extend(
                self._render_stoplist_section(
                    "🟢 Ушли из стопа",
                    delta["removed"],
                    age_days=removed_age_days,
                    removed=True,
                )
            )
            lines.append("")

        if not current_items and not delta["removed"]:
            lines.append("🟢 По сравнению с прошлой проверкой новых изменений нет.")

        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)


point_statistics_service = PointStatisticsService()
