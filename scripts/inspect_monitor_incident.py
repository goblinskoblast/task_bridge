from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import get_db_session
from db.models import (
    DataAgentMonitorConfig,
    DataAgentMonitorEvent,
    DataAgentProfile,
    DataAgentRequestLog,
    User,
)
from data_agent.monitoring import (
    MONITOR_USER_TIMEZONE,
    format_user_facing_chat_label,
    looks_corrupted_user_text,
)


USER_TZ = ZoneInfo(MONITOR_USER_TIMEZONE)
TEXT_FALLBACK = "corrupted_text"


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.isoformat()


def _to_local_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        localized = value.replace(tzinfo=timezone.utc).astimezone(USER_TZ)
    else:
        localized = value.astimezone(USER_TZ)
    return localized.isoformat()


def _safe_text(value: str | None, *, limit: int = 240, fallback: str = TEXT_FALLBACK) -> str | None:
    normalized = " ".join((value or "").split())
    if not normalized:
        return None
    if looks_corrupted_user_text(normalized):
        return fallback
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _compact_result(result: object, *, include_result_json: bool = False) -> dict:
    if not isinstance(result, dict):
        return {}

    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    delta = result.get("delta") if isinstance(result.get("delta"), dict) else {}
    compact = {
        "status": result.get("status"),
        "has_red_flags": result.get("has_red_flags"),
        "alert_hash_present": bool(result.get("alert_hash")),
        "period_hint": _safe_text(result.get("period_hint"), limit=120),
        "matched_period": _safe_text(result.get("matched_period"), limit=120),
        "red_signal_count": result.get("red_signal_count"),
        "slot_count": result.get("slot_count"),
        "table_count": result.get("table_count"),
        "inspected_hours": result.get("inspected_hours"),
        "inspected_slots_count": len(result.get("inspected_slots") or []),
        "items_count": len(result.get("items") or []),
        "delta_added_count": len(delta.get("added") or []),
        "delta_removed_count": len(delta.get("removed") or []),
        "diagnostics_stage": diagnostics.get("stage"),
        "report_excerpt": _safe_text(result.get("report_text"), limit=260),
        "message_excerpt": _safe_text(result.get("message"), limit=180),
    }
    compact = {key: value for key, value in compact.items() if value not in (None, [], {})}
    if include_result_json:
        compact["last_result_json"] = result
    return compact


def _event_group_key(item: DataAgentMonitorEvent) -> str:
    sent = "sent" if item.sent_to_telegram else "unsent"
    return f"{item.monitor_type}:{item.severity}:{sent}"


def _profile_payload(profile: DataAgentProfile | None) -> dict:
    if not profile:
        return {}
    return {
        "default_report_chat_id": getattr(profile, "default_report_chat_id", None),
        "default_report_chat_label": format_user_facing_chat_label(getattr(profile, "default_report_chat_title", None)),
        "blanks_report_chat_id": getattr(profile, "blanks_report_chat_id", None),
        "blanks_report_chat_label": format_user_facing_chat_label(getattr(profile, "blanks_report_chat_title", None)),
        "stoplist_report_chat_id": getattr(profile, "stoplist_report_chat_id", None),
        "stoplist_report_chat_label": format_user_facing_chat_label(getattr(profile, "stoplist_report_chat_title", None)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect recent monitor activity for a Telegram user.")
    parser.add_argument("--telegram-user-id", type=int, required=True)
    parser.add_argument("--since-hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--include-result-json",
        action="store_true",
        help="Include full last_result_json for deep debugging. Default output stays compact.",
    )
    args = parser.parse_args()

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max(1, args.since_hours))

    db = get_db_session()
    try:
        user = db.query(User).filter(User.telegram_id == args.telegram_user_id).first()
        if not user:
            raise RuntimeError(f"user with telegram_id={args.telegram_user_id} not found")

        profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()

        configs = (
            db.query(DataAgentMonitorConfig)
            .filter(DataAgentMonitorConfig.user_id == user.id)
            .order_by(
                DataAgentMonitorConfig.is_active.desc(),
                DataAgentMonitorConfig.monitor_type.asc(),
                DataAgentMonitorConfig.point_name.asc(),
            )
            .all()
        )

        events = (
            db.query(DataAgentMonitorEvent)
            .filter(
                DataAgentMonitorEvent.user_id == user.id,
                DataAgentMonitorEvent.created_at >= since,
            )
            .order_by(DataAgentMonitorEvent.created_at.desc(), DataAgentMonitorEvent.id.desc())
            .limit(max(1, args.limit))
            .all()
        )

        requests = (
            db.query(DataAgentRequestLog)
            .filter(
                DataAgentRequestLog.user_id == user.id,
                DataAgentRequestLog.created_at >= since,
            )
            .order_by(DataAgentRequestLog.created_at.desc(), DataAgentRequestLog.id.desc())
            .limit(max(1, args.limit))
            .all()
        )

        active_configs = [item for item in configs if item.is_active]
        event_counter = Counter(_event_group_key(item) for item in events)
        failed_requests = [item for item in requests if not item.success]
        unsent_critical_blanks = [
            item
            for item in events
            if item.monitor_type == "blanks"
            and item.severity == "critical"
            and not item.sent_to_telegram
        ]

        payload = {
            "telegram_user_id": args.telegram_user_id,
            "user_id": user.id,
            "since_utc": _to_iso(since),
            "since_local": _to_local_iso(since),
            "timezone": MONITOR_USER_TIMEZONE,
            "profile": _profile_payload(profile),
            "summary": {
                "active_configs": len(active_configs),
                "inactive_configs": len(configs) - len(active_configs),
                "recent_events": len(events),
                "recent_requests": len(requests),
                "failed_requests": len(failed_requests),
                "unsent_critical_blanks": len(unsent_critical_blanks),
                "event_groups": dict(sorted(event_counter.items())),
            },
            "configs": [
                {
                    "id": item.id,
                    "monitor_type": item.monitor_type,
                    "point_name": _safe_text(item.point_name, limit=180),
                    "is_active": item.is_active,
                    "check_interval_minutes": item.check_interval_minutes,
                    "active_from_hour": item.active_from_hour,
                    "active_to_hour": item.active_to_hour,
                    "last_checked_at": _to_iso(item.last_checked_at),
                    "last_checked_local": _to_local_iso(item.last_checked_at),
                    "last_status": item.last_status,
                    "last_alert_hash_present": bool(item.last_alert_hash),
                    "result": _compact_result(
                        item.last_result_json,
                        include_result_json=args.include_result_json,
                    ),
                }
                for item in configs
            ],
            "recent_events": [
                {
                    "id": item.id,
                    "config_id": item.config_id,
                    "monitor_type": item.monitor_type,
                    "point_name": _safe_text(item.point_name, limit=180),
                    "severity": item.severity,
                    "title": _safe_text(item.title, limit=180),
                    "body_excerpt": _safe_text(item.body, limit=280),
                    "event_hash_present": bool(item.event_hash),
                    "sent_to_telegram": item.sent_to_telegram,
                    "created_at": _to_iso(item.created_at),
                    "created_local": _to_local_iso(item.created_at),
                }
                for item in events
            ],
            "recent_requests": [
                {
                    "id": item.id,
                    "trace_id": item.trace_id,
                    "user_message": _safe_text(item.user_message, limit=220),
                    "selected_tools": item.selected_tools,
                    "success": item.success,
                    "duration_ms": item.duration_ms,
                    "error_message": _safe_text(item.error_message, limit=180),
                    "created_at": _to_iso(item.created_at),
                    "created_local": _to_local_iso(item.created_at),
                }
                for item in requests
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
