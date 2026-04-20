from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.attention_monitoring import (
    ObservedDelivery,
    ObservedInteraction,
    match_first_reactions,
    summarize_reaction_matches,
)
from data_agent.monitoring import MONITOR_USER_TIMEZONE, looks_corrupted_user_text
from db.database import get_db_session
from db.models import (
    DataAgentMonitorEvent,
    DataAgentRequestLog,
    Message,
    SupportMessage,
    SupportSession,
    User,
)


USER_TZ = ZoneInfo(MONITOR_USER_TIMEZONE)


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _to_local_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(USER_TZ).isoformat()


def _safe_text(value: str | None, *, limit: int = 220) -> str | None:
    normalized = " ".join((value or "").split())
    if not normalized:
        return None
    if looks_corrupted_user_text(normalized):
        return "corrupted_text"
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _delivery_channel(user: User, event: DataAgentMonitorEvent) -> str:
    if event.telegram_chat_id is None:
        return "unknown"
    if int(event.telegram_chat_id) == int(user.telegram_id):
        return "direct_bot_chat"
    return "report_chat"


def _build_deliveries(events: list[DataAgentMonitorEvent]) -> list[ObservedDelivery]:
    deliveries: list[ObservedDelivery] = []
    for event in events:
        if not event.sent_to_telegram or event.telegram_chat_id is None:
            continue
        sent_at = _to_utc_naive(event.telegram_sent_at or event.created_at)
        if sent_at is None:
            continue
        deliveries.append(
            ObservedDelivery(
                id=event.id,
                chat_id=int(event.telegram_chat_id),
                telegram_message_id=event.telegram_message_id,
                sent_at=sent_at,
                source=f"monitor:{event.monitor_type}:{event.severity}",
                title=event.title,
            )
        )
    return deliveries


def _build_interactions(messages: list[Message]) -> list[ObservedInteraction]:
    interactions: list[ObservedInteraction] = []
    for item in messages:
        observed_at = _to_utc_naive(item.date or item.created_at)
        if observed_at is None:
            continue
        interactions.append(
            ObservedInteraction(
                id=item.id,
                chat_id=int(item.chat_id),
                observed_at=observed_at,
                source="telegram_message",
                text=item.text,
                reply_to_message_id=item.reply_to_message_id,
                reply_to_from_bot=item.reply_to_from_bot,
                is_forwarded=bool(item.is_forwarded),
                forward_origin_type=item.forward_origin_type,
                forward_origin_title=item.forward_origin_title,
                forward_from_bot=item.forward_from_bot,
            )
        )
    return interactions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect observable attention signals for the priority Telegram user."
    )
    parser.add_argument("--telegram-user-id", type=int, default=137236883)
    parser.add_argument("--since-hours", type=int, default=168)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-latency-hours", type=int, default=72)
    args = parser.parse_args()

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max(1, args.since_hours))
    db = get_db_session()
    try:
        user = db.query(User).filter(User.telegram_id == args.telegram_user_id).first()
        if not user:
            raise RuntimeError(f"user with telegram_id={args.telegram_user_id} not found")

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
        messages = (
            db.query(Message)
            .filter(
                Message.user_id == user.id,
                Message.date >= since,
            )
            .order_by(Message.date.asc(), Message.id.asc())
            .limit(max(1, args.limit * 3))
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
        support_messages = (
            db.query(SupportMessage)
            .join(SupportSession, SupportSession.id == SupportMessage.session_id)
            .filter(
                SupportSession.user_id == user.id,
                SupportMessage.created_at >= since,
            )
            .order_by(SupportMessage.created_at.desc(), SupportMessage.id.desc())
            .limit(max(1, args.limit))
            .all()
        )

        deliveries = _build_deliveries(events)
        interactions = _build_interactions(messages)
        matches = match_first_reactions(
            deliveries,
            interactions,
            max_latency_hours=args.max_latency_hours,
        )
        visible_forwarded = [item for item in messages if item.is_forwarded]
        linked_events = [
            item for item in events if item.sent_to_telegram and item.telegram_chat_id is not None
        ]
        sent_events = [item for item in events if item.sent_to_telegram]

        payload = {
            "telegram_user_id": args.telegram_user_id,
            "user_id": user.id,
            "timezone": MONITOR_USER_TIMEZONE,
            "since_utc": since.isoformat(),
            "since_local": _to_local_iso(since),
            "capabilities": {
                "telegram_direct_read_receipts": {
                    "available": False,
                    "note": "Regular Telegram Bot API updates do not expose when a user has read an outgoing bot message.",
                },
                "observed_attention_latency": {
                    "available": True,
                    "note": "Measured as post -> first visible user action in the same chat, not as true seen/read.",
                },
                "forward_detection": {
                    "available": True,
                    "scope": "Only forwards that arrive into a chat visible to the bot can be detected.",
                },
            },
            "summary": {
                "monitor_events": len(events),
                "sent_monitor_events": len(sent_events),
                "delivery_linked_events": len(linked_events),
                "delivery_linkage_coverage": (
                    round(len(linked_events) / len(sent_events), 3) if sent_events else None
                ),
                "report_chat_deliveries": sum(1 for item in linked_events if _delivery_channel(user, item) == "report_chat"),
                "direct_bot_chat_deliveries": sum(1 for item in linked_events if _delivery_channel(user, item) == "direct_bot_chat"),
                "visible_user_messages": len(messages),
                "visible_forwarded_messages": len(visible_forwarded),
                "data_agent_requests": len(requests),
                "support_messages": len(support_messages),
                "attention": summarize_reaction_matches(matches),
            },
            "attention_matches": [
                {
                    "event_id": item.delivery.id,
                    "source": item.delivery.source,
                    "title": _safe_text(item.delivery.title),
                    "delivery_chat_id": item.delivery.chat_id,
                    "delivery_message_id": item.delivery.telegram_message_id,
                    "sent_local": _to_local_iso(item.delivery.sent_at),
                    "match_type": item.match_type,
                    "latency_minutes": item.latency_minutes,
                    "interaction_id": item.interaction.id if item.interaction else None,
                    "interaction_local": _to_local_iso(item.interaction.observed_at) if item.interaction else None,
                    "interaction_text": _safe_text(item.interaction.text) if item.interaction else None,
                    "interaction_forwarded": item.interaction.is_forwarded if item.interaction else None,
                }
                for item in matches[: max(1, args.limit)]
            ],
            "visible_forwards": [
                {
                    "message_id": item.id,
                    "chat_id": item.chat_id,
                    "telegram_message_id": item.message_id,
                    "observed_local": _to_local_iso(item.date),
                    "origin_type": item.forward_origin_type,
                    "origin_title": _safe_text(item.forward_origin_title),
                    "forward_from_bot": item.forward_from_bot,
                    "text": _safe_text(item.text),
                }
                for item in visible_forwarded[:20]
            ],
            "direct_bot_activity": {
                "recent_data_agent_requests": [
                    {
                        "id": item.id,
                        "created_local": _to_local_iso(item.created_at),
                        "success": item.success,
                        "duration_ms": item.duration_ms,
                        "text": _safe_text(item.user_message),
                    }
                    for item in requests[:20]
                ],
                "recent_support_messages": [
                    {
                        "id": item.id,
                        "from_user": item.from_user,
                        "created_local": _to_local_iso(item.created_at),
                        "telegram_message_id": item.telegram_message_id,
                        "text": _safe_text(item.message_text),
                    }
                    for item in support_messages[:20]
                ],
            },
            "limitations": [
                "This report cannot prove that a user read a bot message; it can only show the next action visible to the bot.",
                "Forwarding is invisible unless the forwarded message appears in a chat where the bot receives updates.",
                "Older monitor events before delivery telemetry deployment may have sent_to_telegram=True but no telegram_chat_id/message_id.",
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
