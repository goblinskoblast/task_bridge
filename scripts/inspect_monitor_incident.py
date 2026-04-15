from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect recent monitor activity for a Telegram user.")
    parser.add_argument("--telegram-user-id", type=int, required=True)
    parser.add_argument("--since-hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    since = datetime.utcnow() - timedelta(hours=max(1, args.since_hours))

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

        payload = {
            "telegram_user_id": args.telegram_user_id,
            "user_id": user.id,
            "since_utc": _to_iso(since),
            "profile": {
                "default_report_chat_id": getattr(profile, "default_report_chat_id", None),
                "default_report_chat_title": getattr(profile, "default_report_chat_title", None),
                "blanks_report_chat_id": getattr(profile, "blanks_report_chat_id", None),
                "blanks_report_chat_title": getattr(profile, "blanks_report_chat_title", None),
                "stoplist_report_chat_id": getattr(profile, "stoplist_report_chat_id", None),
                "stoplist_report_chat_title": getattr(profile, "stoplist_report_chat_title", None),
            },
            "configs": [
                {
                    "id": item.id,
                    "monitor_type": item.monitor_type,
                    "point_name": item.point_name,
                    "is_active": item.is_active,
                    "check_interval_minutes": item.check_interval_minutes,
                    "active_from_hour": item.active_from_hour,
                    "active_to_hour": item.active_to_hour,
                    "last_checked_at": _to_iso(item.last_checked_at),
                    "last_status": item.last_status,
                    "last_alert_hash": item.last_alert_hash,
                    "last_result_json": item.last_result_json,
                }
                for item in configs
            ],
            "recent_events": [
                {
                    "id": item.id,
                    "config_id": item.config_id,
                    "monitor_type": item.monitor_type,
                    "point_name": item.point_name,
                    "severity": item.severity,
                    "title": item.title,
                    "body_excerpt": (item.body or "")[:400],
                    "event_hash": item.event_hash,
                    "sent_to_telegram": item.sent_to_telegram,
                    "created_at": _to_iso(item.created_at),
                }
                for item in events
            ],
            "recent_requests": [
                {
                    "id": item.id,
                    "trace_id": item.trace_id,
                    "user_message": item.user_message,
                    "selected_tools": item.selected_tools,
                    "success": item.success,
                    "duration_ms": item.duration_ms,
                    "error_message": item.error_message,
                    "created_at": _to_iso(item.created_at),
                }
                for item in requests
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
