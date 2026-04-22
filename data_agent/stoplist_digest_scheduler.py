from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytz
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    BOT_TOKEN,
    STOPLIST_WEEKLY_DIGEST_DAY_OF_WEEK,
    STOPLIST_WEEKLY_DIGEST_HOUR,
    STOPLIST_WEEKLY_DIGEST_LOOKBACK_DAYS,
    STOPLIST_WEEKLY_DIGEST_MINUTE,
    STOPLIST_WEEKLY_DIGESTS_ENABLED,
    TIMEZONE,
)
from db.database import get_db_session
from db.models import (
    DataAgentMonitorConfig,
    DataAgentProfile,
    StopListIncident,
    StopListWeeklyDigestDelivery,
    User,
)

from .stoplist_digest import build_stoplist_digest_snapshot, format_stoplist_digest_text

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


@dataclass(frozen=True)
class StopListWeeklyDigestCandidate:
    user_id: int
    telegram_user_id: int
    chat_id: int
    chat_title: str | None
    delivery_target: str
    week_start_date: date
    text: str
    digest_hash: str
    incidents_count: int
    affected_points_count: int
    recurring_points_count: int
    need_attention_points_count: int


def _coerce_local_now(now: datetime | None) -> datetime:
    timezone = pytz.timezone(TIMEZONE)
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return timezone.localize(now)
    return now.astimezone(timezone)


def _utc_naive(now_local: datetime) -> datetime:
    return now_local.astimezone(pytz.UTC).replace(tzinfo=None)


def _normalize_sent_at(value: Any, *, fallback: datetime) -> datetime:
    if not isinstance(value, datetime):
        return fallback
    if value.tzinfo is None:
        return value
    return value.astimezone(pytz.UTC).replace(tzinfo=None)


def _week_start_date(now_local: datetime) -> date:
    return (now_local - timedelta(days=now_local.weekday())).date()


def _resolve_delivery_target(
    *,
    profile: DataAgentProfile | None,
    user: User,
) -> tuple[int | None, str | None, str]:
    if profile and profile.stoplist_report_chat_id:
        return (
            int(profile.stoplist_report_chat_id),
            str(profile.stoplist_report_chat_title or "").strip() or None,
            "profile_stoplist_chat",
        )
    if profile and profile.default_report_chat_id:
        return (
            int(profile.default_report_chat_id),
            str(profile.default_report_chat_title or "").strip() or None,
            "profile_default_chat",
        )
    if user.telegram_id and user.telegram_id != -1:
        return int(user.telegram_id), None, "direct_bot_chat"
    return None, None, "unresolved"


def _build_digest_text(*, lookback_days: int, snapshot) -> str:
    body = format_stoplist_digest_text(snapshot)
    return (
        "Еженедельный дайджест по стоп-листу\n\n"
        f"{body}\n\n"
        f"Окно: последние {lookback_days} дней."
    ).strip()


def _build_candidate_for_user(
    db,
    *,
    user: User,
    profile: DataAgentProfile | None,
    now_local: datetime,
    lookback_days: int,
    week_start: date,
    ignore_existing_delivery: bool = False,
) -> StopListWeeklyDigestCandidate | None:
    now_local = _coerce_local_now(now_local)
    if not ignore_existing_delivery:
        existing_delivery = (
            db.query(StopListWeeklyDigestDelivery)
            .filter(
                StopListWeeklyDigestDelivery.user_id == user.id,
                StopListWeeklyDigestDelivery.week_start_date == week_start,
            )
            .first()
        )
        if existing_delivery:
            return None

    chat_id, chat_title, delivery_target = _resolve_delivery_target(profile=profile, user=user)
    if not chat_id:
        return None

    since_utc = _utc_naive(now_local) - timedelta(days=max(int(lookback_days or 7), 1))
    incidents = (
        db.query(StopListIncident)
        .filter(
            StopListIncident.user_id == user.id,
            StopListIncident.last_seen_at >= since_utc,
        )
        .order_by(StopListIncident.point_name.asc(), StopListIncident.last_seen_at.desc(), StopListIncident.id.desc())
        .all()
    )
    if not incidents:
        return None

    snapshot = build_stoplist_digest_snapshot(
        incidents,
        days=max(int(lookback_days or 7), 1),
        now=_utc_naive(now_local),
    )
    if snapshot.total_incidents <= 0:
        return None

    text = _build_digest_text(lookback_days=max(int(lookback_days or 7), 1), snapshot=snapshot)
    digest_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return StopListWeeklyDigestCandidate(
        user_id=int(user.id),
        telegram_user_id=int(user.telegram_id),
        chat_id=int(chat_id),
        chat_title=chat_title,
        delivery_target=delivery_target,
        week_start_date=week_start,
        text=text,
        digest_hash=digest_hash,
        incidents_count=int(snapshot.total_incidents),
        affected_points_count=int(snapshot.affected_points),
        recurring_points_count=int(snapshot.recurring_points),
        need_attention_points_count=int(snapshot.need_attention_points),
    )


def _build_due_stoplist_weekly_digest_candidates(
    db,
    *,
    now_local: datetime,
    lookback_days: int,
) -> list[StopListWeeklyDigestCandidate]:
    now_local = _coerce_local_now(now_local)
    week_start = _week_start_date(now_local)
    user_ids = [
        int(item[0])
        for item in (
            db.query(DataAgentMonitorConfig.user_id)
            .filter(
                DataAgentMonitorConfig.monitor_type == "stoplist",
                DataAgentMonitorConfig.is_active.is_(True),
            )
            .distinct()
            .all()
        )
    ]
    if not user_ids:
        return []

    users = db.query(User).filter(User.id.in_(user_ids)).all()
    profiles = db.query(DataAgentProfile).filter(DataAgentProfile.user_id.in_(user_ids)).all()
    profiles_by_user_id = {int(item.user_id): item for item in profiles}

    candidates: list[StopListWeeklyDigestCandidate] = []
    for user in users:
        candidate = _build_candidate_for_user(
            db,
            user=user,
            profile=profiles_by_user_id.get(int(user.id)),
            now_local=now_local,
            lookback_days=lookback_days,
            week_start=week_start,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def build_stoplist_weekly_digest_preview(
    *,
    telegram_user_id: int,
    now: datetime | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    db = get_db_session()
    try:
        now_local = _coerce_local_now(now)
        lookback = max(int(lookback_days or STOPLIST_WEEKLY_DIGEST_LOOKBACK_DAYS or 7), 1)
        week_start = _week_start_date(now_local)
        user = db.query(User).filter(User.telegram_id == telegram_user_id).first()
        if not user:
            return {
                "found": False,
                "status": "user_not_found",
                "telegram_user_id": telegram_user_id,
            }

        profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
        already_delivered = (
            db.query(StopListWeeklyDigestDelivery)
            .filter(
                StopListWeeklyDigestDelivery.user_id == user.id,
                StopListWeeklyDigestDelivery.week_start_date == week_start,
            )
            .first()
        )
        candidate = _build_candidate_for_user(
            db,
            user=user,
            profile=profile,
            now_local=now_local,
            lookback_days=lookback,
            week_start=week_start,
            ignore_existing_delivery=True,
        )
        if candidate is None:
            chat_id, chat_title, delivery_target = _resolve_delivery_target(profile=profile, user=user)
            return {
                "found": True,
                "status": "empty",
                "user_id": int(user.id),
                "telegram_user_id": int(user.telegram_id),
                "week_start_date": week_start.isoformat(),
                "already_delivered_this_week": already_delivered is not None,
                "delivery_chat_id": chat_id,
                "delivery_chat_title": chat_title,
                "delivery_target": delivery_target,
            }

        return {
            "found": True,
            "status": "ready",
            "user_id": int(user.id),
            "telegram_user_id": int(user.telegram_id),
            "week_start_date": candidate.week_start_date.isoformat(),
            "already_delivered_this_week": already_delivered is not None,
            "delivery_chat_id": candidate.chat_id,
            "delivery_chat_title": candidate.chat_title,
            "delivery_target": candidate.delivery_target,
            "incidents_count": candidate.incidents_count,
            "affected_points_count": candidate.affected_points_count,
            "recurring_points_count": candidate.recurring_points_count,
            "need_attention_points_count": candidate.need_attention_points_count,
            "text": candidate.text,
        }
    finally:
        db.close()


async def send_due_stoplist_weekly_digests(
    bot: Bot,
    *,
    now: datetime | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    db = get_db_session()
    try:
        now_local = _coerce_local_now(now)
        lookback = max(int(lookback_days or STOPLIST_WEEKLY_DIGEST_LOOKBACK_DAYS or 7), 1)
        candidates = _build_due_stoplist_weekly_digest_candidates(
            db,
            now_local=now_local,
            lookback_days=lookback,
        )
        sent = 0
        failed = 0
        for candidate in candidates:
            try:
                sent_message = await bot.send_message(
                    chat_id=candidate.chat_id,
                    text=candidate.text,
                )
                db.add(
                    StopListWeeklyDigestDelivery(
                        user_id=candidate.user_id,
                        week_start_date=candidate.week_start_date,
                        digest_window_days=lookback,
                        chat_id=candidate.chat_id,
                        telegram_message_id=getattr(sent_message, "message_id", None),
                        digest_hash=candidate.digest_hash,
                        incidents_count=candidate.incidents_count,
                        affected_points_count=candidate.affected_points_count,
                        recurring_points_count=candidate.recurring_points_count,
                        need_attention_points_count=candidate.need_attention_points_count,
                        sent_at=_normalize_sent_at(
                            getattr(sent_message, "date", None),
                            fallback=_utc_naive(now_local),
                        ),
                    )
                )
                db.commit()
                sent += 1
            except Exception:
                db.rollback()
                failed += 1
                logger.exception(
                    "Failed to deliver weekly stoplist digest user_id=%s chat_id=%s",
                    candidate.user_id,
                    candidate.chat_id,
                )
        logger.info(
            "Weekly stoplist digests finished candidates=%s sent=%s failed=%s",
            len(candidates),
            sent,
            failed,
        )
        return {
            "status": "ok",
            "candidates": len(candidates),
            "sent": sent,
            "failed": failed,
            "week_start_date": _week_start_date(now_local).isoformat(),
        }
    finally:
        db.close()


async def _run_scheduled_stoplist_weekly_digests(bot: Bot) -> None:
    await send_due_stoplist_weekly_digests(bot)


def start_stoplist_digest_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if not STOPLIST_WEEKLY_DIGESTS_ENABLED:
        logger.info("Stoplist weekly digest scheduler is disabled by config")
        return

    bot = Bot(token=BOT_TOKEN)
    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _scheduler.add_job(
        _run_scheduled_stoplist_weekly_digests,
        "cron",
        day_of_week=STOPLIST_WEEKLY_DIGEST_DAY_OF_WEEK,
        hour=STOPLIST_WEEKLY_DIGEST_HOUR,
        minute=STOPLIST_WEEKLY_DIGEST_MINUTE,
        args=[bot],
        id="stoplist_weekly_digest",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Stoplist weekly digest scheduler started day_of_week=%s hour=%s minute=%s",
        STOPLIST_WEEKLY_DIGEST_DAY_OF_WEEK,
        STOPLIST_WEEKLY_DIGEST_HOUR,
        STOPLIST_WEEKLY_DIGEST_MINUTE,
    )


def stop_stoplist_digest_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
