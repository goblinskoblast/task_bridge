from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TIMEZONE

from .point_statistics import point_statistics_service

logger = logging.getLogger(__name__)

_point_stats_scheduler: AsyncIOScheduler | None = None


async def _run_point_statistics() -> None:
    result = await point_statistics_service.collect_due_points()
    logger.info(
        'Point statistics collector finished status=%s runs=%s snapshots=%s',
        result.get('status'),
        result.get('runs', 0),
        result.get('snapshots', 0),
    )


def start_point_statistics_scheduler() -> None:
    global _point_stats_scheduler
    if _point_stats_scheduler is not None:
        return

    _point_stats_scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _point_stats_scheduler.add_job(
        _run_point_statistics,
        'interval',
        minutes=60,
        id='point_statistics',
        replace_existing=True,
    )
    _point_stats_scheduler.start()
    logger.info('Point statistics scheduler started with interval 60 minutes')


def stop_point_statistics_scheduler() -> None:
    global _point_stats_scheduler
    if _point_stats_scheduler is not None:
        _point_stats_scheduler.shutdown()
        _point_stats_scheduler = None
