from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import get_db_session, init_db
from db.models import Chat, DataAgentMonitorConfig, SavedPoint, User
from data_agent.point_delivery import match_saved_point_to_chat_title


def _active_group_chats(db) -> list[Chat]:
    return (
        db.query(Chat)
        .filter(
            Chat.is_active.is_(True),
            Chat.chat_type.in_(["group", "supergroup"]),
        )
        .order_by(Chat.updated_at.desc(), Chat.title.asc())
        .all()
    )


def _build_stoplist_template(db, user_id: int) -> dict[str, int | None]:
    template = (
        db.query(DataAgentMonitorConfig)
        .filter(
            DataAgentMonitorConfig.user_id == user_id,
            DataAgentMonitorConfig.monitor_type == "stoplist",
            DataAgentMonitorConfig.is_active.is_(True),
        )
        .order_by(DataAgentMonitorConfig.id.asc())
        .first()
    )
    if template:
        return {
            "interval": template.check_interval_minutes,
            "active_from_hour": template.active_from_hour,
            "active_to_hour": template.active_to_hour,
        }
    return {
        "interval": 180,
        "active_from_hour": 8,
        "active_to_hour": 20,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure point-specific routing for the priority user.")
    parser.add_argument("--telegram-user-id", type=int, default=137236883)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    init_db()
    db = get_db_session()
    try:
        user = db.query(User).filter(User.telegram_id == args.telegram_user_id).first()
        if not user:
            raise RuntimeError(f"user with telegram_id={args.telegram_user_id} not found")

        points = (
            db.query(SavedPoint)
            .filter(SavedPoint.user_id == user.id, SavedPoint.is_active.is_(True))
            .order_by(SavedPoint.display_name.asc())
            .all()
        )
        chats = _active_group_chats(db)
        stoplist_template = _build_stoplist_template(db, user.id)

        matched_pairs: list[dict[str, object]] = []
        unmatched_chats: list[dict[str, object]] = []
        configured_point_ids: set[int] = set()

        for chat in chats:
            point = match_saved_point_to_chat_title(points, chat.title)
            if not point:
                unmatched_chats.append({"chat_id": chat.chat_id, "title": chat.title})
                continue

            configured_point_ids.add(point.id)
            matched_pairs.append(
                {
                    "point_id": point.id,
                    "point_name": point.display_name,
                    "chat_id": chat.chat_id,
                    "chat_title": chat.title,
                }
            )

            if args.apply:
                point.report_delivery_enabled = True
                point.stoplist_report_chat_id = chat.chat_id
                point.stoplist_report_chat_title = chat.title
                point.blanks_report_chat_id = chat.chat_id
                point.blanks_report_chat_title = chat.title

                blanks_monitor = (
                    db.query(DataAgentMonitorConfig)
                    .filter(
                        DataAgentMonitorConfig.user_id == user.id,
                        DataAgentMonitorConfig.monitor_type == "blanks",
                        DataAgentMonitorConfig.point_name == point.display_name,
                    )
                    .first()
                )
                if blanks_monitor:
                    blanks_monitor.is_active = True

                stoplist_monitor = (
                    db.query(DataAgentMonitorConfig)
                    .filter(
                        DataAgentMonitorConfig.user_id == user.id,
                        DataAgentMonitorConfig.monitor_type == "stoplist",
                        DataAgentMonitorConfig.point_name == point.display_name,
                    )
                    .first()
                )
                if not stoplist_monitor:
                    db.add(
                        DataAgentMonitorConfig(
                            user_id=user.id,
                            system_name="italian_pizza",
                            monitor_type="stoplist",
                            point_name=point.display_name,
                            point_address=point.address,
                            check_interval_minutes=int(stoplist_template["interval"] or 180),
                            is_active=True,
                            active_from_hour=stoplist_template["active_from_hour"],
                            active_to_hour=stoplist_template["active_to_hour"],
                        )
                    )
                else:
                    stoplist_monitor.is_active = True

        if args.apply:
            db.commit()

        unmatched_points = [
            {"point_id": point.id, "point_name": point.display_name}
            for point in points
            if point.id not in configured_point_ids
        ]

        payload = {
            "telegram_user_id": args.telegram_user_id,
            "apply": args.apply,
            "matched_pairs": matched_pairs,
            "unmatched_chats": unmatched_chats,
            "unmatched_points": unmatched_points,
            "stoplist_template": stoplist_template,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
