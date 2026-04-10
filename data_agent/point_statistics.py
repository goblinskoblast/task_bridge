from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from db.database import get_db_session
from db.models import DataAgentSystem, PointStatRun, PointStatSnapshot, SavedPoint, User

from .blanks_tool import blanks_tool
from .italian_pizza import resolve_italian_pizza_point
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)


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

            previous_snapshot = self._get_latest_snapshot(db, point.id)
            previous_items = self._normalize_items(previous_snapshot.stoplist_items_json if previous_snapshot else [])
            delta = self._compute_stoplist_delta(previous_items, current_items)

            enriched["delta"] = delta
            enriched["report_text"] = self._render_stoplist_report(
                point_name=point.display_name,
                current_items=current_items,
                delta=delta,
                has_history=previous_snapshot is not None,
                is_saved_point=True,
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

    def _render_stoplist_report(
        self,
        point_name: str,
        current_items: list[str],
        delta: dict[str, list[str]],
        *,
        has_history: bool,
        is_saved_point: bool,
    ) -> str:
        lines = [f"📍 Точка: {point_name}"]

        if current_items:
            lines.append(f"🚫 Сейчас в стоп-листе: {len(current_items)}")
            if has_history and is_saved_point:
                added_set = set(delta["added"])
                stayed_set = set(delta["stayed"])
                for item in current_items:
                    if item in added_set:
                        lines.append(f"🆕 {item}")
                    elif item in stayed_set:
                        lines.append(f"🔁 {item}")
                    else:
                        lines.append(f"• {item}")
            else:
                lines.extend(f"• {item}" for item in current_items)
        else:
            lines.append("✅ Сейчас в стоп-листе недоступных позиций нет.")

        lines.append("")
        if not is_saved_point:
            lines.append("ℹ️ Чтобы видеть динамику изменений, сохраните эту точку в боте.")
            return "\n".join(lines)

        if not has_history:
            lines.append("🕓 Динамика появится после следующей проверки этой точки.")
            return "\n".join(lines)

        if delta["removed"]:
            lines.append(f"✅ Ушли из стоп-листа: {len(delta['removed'])}")
            lines.extend(f"• {item}" for item in delta["removed"])
            lines.append("")

        if not delta["added"] and not delta["removed"]:
            lines.append("🟰 По сравнению с прошлой проверкой изменений нет.")

        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)


point_statistics_service = PointStatisticsService()
