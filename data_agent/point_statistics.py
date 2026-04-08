from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from db.database import get_db_session
from db.models import DataAgentSystem, PointStatRun, PointStatSnapshot, SavedPoint

from .blanks_tool import blanks_tool
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
        run = PointStatRun(user_id=user_id, status='running', run_started_at=datetime.utcnow())
        db.add(run)
        db.commit()
        db.refresh(run)

        snapshots_created = 0
        had_errors = False
        try:
            system = self._find_italian_pizza_system(db, user_id)
            for point in points:
                snapshot = await self._collect_point_snapshot(db, run, point, system)
                if snapshot.source_error:
                    had_errors = True
                snapshots_created += 1
            run.status = 'completed_with_errors' if had_errors else 'completed'
            run.run_finished_at = datetime.utcnow()
            db.commit()
            return snapshots_created
        except Exception as exc:
            db.rollback()
            logger.error('Point statistics run failed user_id=%s error=%s', user_id, exc, exc_info=True)
            run.status = 'failed'
            run.error_text = str(exc)
            run.run_finished_at = datetime.utcnow()
            db.add(run)
            db.commit()
            return snapshots_created

    async def _collect_point_snapshot(self, db: Session, run: PointStatRun, point: SavedPoint, system: DataAgentSystem | None) -> PointStatSnapshot:
        stoplist_result = await stoplist_tool.collect_for_point(
            url='',
            username='',
            encrypted_password='',
            point_name=point.display_name,
        )
        stoplist_items = self._extract_stoplist_items(stoplist_result)
        source_errors: list[str] = []
        if (stoplist_result.get('status') or '').lower() not in {'ok', 'completed'}:
            source_errors.append(str(stoplist_result.get('message') or stoplist_result.get('report_text') or 'stoplist_failed'))

        blanks_total_count = 0
        blanks_red_count = 0
        blanks_items: list[str] = []
        if system:
            blanks_result = await blanks_tool.inspect_point(
                url=system.url,
                username=system.login,
                encrypted_password=system.encrypted_password,
                point_name=point.display_name,
                period_hint='предыдущие 12 часов',
            )
            diagnostics = blanks_result.get('diagnostics') or {}
            blanks_total_count = int(diagnostics.get('slot_count') or diagnostics.get('table_count') or 0)
            blanks_red_count = int(diagnostics.get('red_signal_count') or 0)
            blanks_items = self._extract_blanks_items(blanks_result)
            if (blanks_result.get('status') or '').lower() not in {'ok', 'completed'}:
                source_errors.append(str(blanks_result.get('message') or blanks_result.get('report_text') or 'blanks_failed'))
        else:
            source_errors.append('italian_pizza_system_not_connected')

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
            source_error='; '.join(source_errors) if source_errors else None,
        )
        db.add(snapshot)
        point.last_stats_collected_at = snapshot.snapshot_at
        db.commit()
        db.refresh(snapshot)
        logger.info(
            'Point statistics snapshot saved user_id=%s point=%s stoplist=%s blanks_red=%s source_ok=%s',
            run.user_id,
            point.display_name,
            snapshot.stoplist_count,
            snapshot.blanks_red_count,
            snapshot.source_ok,
        )
        return snapshot

    def _find_italian_pizza_system(self, db: Session, user_id: int) -> DataAgentSystem | None:
        return (
            db.query(DataAgentSystem)
            .filter(
                DataAgentSystem.user_id == user_id,
                DataAgentSystem.is_active.is_(True),
                (DataAgentSystem.system_name == 'italian_pizza') | (DataAgentSystem.url.contains('italianpizza')),
            )
            .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
            .first()
        )

    def _extract_stoplist_items(self, result: dict) -> list[str]:
        report_text = str(result.get('report_text') or '')
        items: list[str] = []
        for line in report_text.splitlines():
            stripped = line.strip()
            if stripped.startswith('- '):
                item = stripped[2:].strip()
                if item and item not in items:
                    items.append(item)
        return items

    def _extract_blanks_items(self, result: dict) -> list[str]:
        diagnostics = result.get('diagnostics') or {}
        values: list[str] = []
        for key in ('styled_cell_samples', 'table_samples', 'inspected_slots'):
            data = diagnostics.get(key) or []
            if isinstance(data, list):
                for item in data:
                    normalized = str(item).strip()
                    if normalized and normalized not in values:
                        values.append(normalized)
        return values[:30]


point_statistics_service = PointStatisticsService()
