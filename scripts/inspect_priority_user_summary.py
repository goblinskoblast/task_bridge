from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.attention_monitoring import match_first_reactions, summarize_reaction_matches
from db.database import get_db_session
from db.models import (
    DataAgentMonitorConfig,
    DataAgentMonitorEvent,
    DataAgentProfile,
    DataAgentRequestLog,
    Message,
    SupportMessage,
    SupportSession,
    User,
)
from scripts.inspect_monitor_incident import (
    _compact_result,
    _profile_payload,
    _safe_text,
    _to_iso,
    _to_local_iso,
)
from scripts.inspect_priority_user_attention import (
    _build_deliveries,
    _build_interactions,
    _delivery_channel,
)


_RETRY_STATUSES = {
    "failed",
    "error",
    "system_not_connected",
    "no_systems_connected",
    "system_not_found",
    "needs_point",
    "needs_period",
    "awaiting_user_input",
    "not_configured",
}


def _monitor_state(item: DataAgentMonitorConfig) -> str:
    result = item.last_result_json if isinstance(item.last_result_json, dict) else {}
    if item.monitor_type == "blanks" and result.get("has_red_flags"):
        return "alert"

    normalized = (item.last_status or "").strip().lower()
    if not normalized:
        return "pending"
    if normalized in {"ok", "completed"}:
        return "ok"
    if normalized in _RETRY_STATUSES:
        return "retry"
    return "other"


def _event_group_key(item: DataAgentMonitorEvent) -> str:
    sent = "sent" if item.sent_to_telegram else "unsent"
    return f"{item.monitor_type}:{item.severity}:{sent}"


def _event_point_label(item: DataAgentMonitorEvent) -> str:
    return _safe_text(item.point_name, limit=140) or "точка не указана"


def _build_executive_summary(
    *,
    since_hours: int,
    active_configs: list[DataAgentMonitorConfig],
    events: list[DataAgentMonitorEvent],
    linked_events: list[DataAgentMonitorEvent],
    requests: list[DataAgentRequestLog],
    visible_messages: list[Message],
    visible_forwarded: list[Message],
    user_support_messages: list[SupportMessage],
    attention_matches: list,
) -> list[str]:
    event_groups = Counter(_event_group_key(item) for item in events)
    state_counts = Counter(_monitor_state(item) for item in active_configs)
    current_alert_points = [
        _safe_text(item.point_name, limit=120) or "точка не указана"
        for item in active_configs
        if _monitor_state(item) == "alert"
    ]
    attention_summary = summarize_reaction_matches(attention_matches)

    delivered_parts: list[str] = []
    for key, label in (
        ("blanks:critical:sent", "critical blanks"),
        ("stoplist:info:sent", "stoplist"),
        ("reviews:info:sent", "reviews"),
    ):
        count = event_groups.get(key)
        if count:
            delivered_parts.append(f"{count} {label}")

    lines = [
        (
            f"За последние {since_hours} ч: отправлено monitor-событий {len(events)}"
            + (f" ({', '.join(delivered_parts)})" if delivered_parts else "")
            + "."
        ),
        (
            f"Активных мониторингов: {len(active_configs)}; "
            f"с красной зоной сейчас: {state_counts.get('alert', 0)}; "
            f"нуждаются в повторной проверке: {state_counts.get('retry', 0)}."
        ),
    ]
    if current_alert_points:
        lines.append("Текущая красная зона: " + "; ".join(current_alert_points) + ".")
    lines.append(
        f"Видимые действия пользователя: {len(visible_messages)} Telegram-сообщений, "
        f"{len(requests)} agent-запросов, {len(user_support_messages)} сообщений в поддержку, "
        f"{len(visible_forwarded)} пересылок."
    )
    lines.append(
        f"Delivery linkage: {len(linked_events)} из {len(events)} sent-событий; "
        f"видимых реакций после доставки: {attention_summary.get('matched_visible_reactions', 0)}."
    )
    lines.append(
        "Telegram Bot API не показывает точное прочтение исходящих сообщений; "
        "доступно только первое действие, которое бот увидел после доставки."
    )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combined production summary for the priority Telegram user."
    )
    parser.add_argument("--telegram-user-id", type=int, default=137236883)
    parser.add_argument("--since-hours", type=int, default=72)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--max-latency-hours", type=int, default=72)
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
        visible_messages = (
            db.query(Message)
            .filter(
                Message.user_id == user.id,
                Message.date >= since,
            )
            .order_by(Message.date.desc(), Message.id.desc())
            .limit(max(1, args.limit * 3))
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

        user_support_messages = [item for item in support_messages if item.from_user]
        bot_support_messages = [item for item in support_messages if not item.from_user]
        active_configs = [item for item in configs if item.is_active]
        linked_events = [
            item for item in events if item.sent_to_telegram and item.telegram_chat_id is not None
        ]
        visible_forwarded = [item for item in visible_messages if item.is_forwarded]
        deliveries = _build_deliveries(events)
        interactions = _build_interactions(list(reversed(visible_messages)))
        attention_matches = match_first_reactions(
            deliveries,
            interactions,
            max_latency_hours=args.max_latency_hours,
        )

        payload = {
            "telegram_user_id": args.telegram_user_id,
            "user_id": user.id,
            "since_utc": _to_iso(since),
            "since_local": _to_local_iso(since),
            "profile": _profile_payload(profile),
            "executive_summary": _build_executive_summary(
                since_hours=args.since_hours,
                active_configs=active_configs,
                events=events,
                linked_events=linked_events,
                requests=requests,
                visible_messages=visible_messages,
                visible_forwarded=visible_forwarded,
                user_support_messages=user_support_messages,
                attention_matches=attention_matches,
            ),
            "what_came": {
                "summary": {
                    "active_monitor_configs": len(active_configs),
                    "monitor_state_counts": dict(sorted(Counter(_monitor_state(item) for item in active_configs).items())),
                    "monitor_event_groups": dict(sorted(Counter(_event_group_key(item) for item in events).items())),
                    "sent_events": sum(1 for item in events if item.sent_to_telegram),
                    "delivery_linked_events": len(linked_events),
                    "report_chat_deliveries": sum(
                        1 for item in linked_events if _delivery_channel(user, item) == "report_chat"
                    ),
                    "direct_bot_chat_deliveries": sum(
                        1 for item in linked_events if _delivery_channel(user, item) == "direct_bot_chat"
                    ),
                    "current_alert_points": [
                        _safe_text(item.point_name, limit=140) or "точка не указана"
                        for item in active_configs
                        if _monitor_state(item) == "alert"
                    ],
                    "retry_points": [
                        _safe_text(item.point_name, limit=140) or "точка не указана"
                        for item in active_configs
                        if _monitor_state(item) == "retry"
                    ],
                },
                "active_monitors": [
                    {
                        "id": item.id,
                        "monitor_type": item.monitor_type,
                        "point_name": _safe_text(item.point_name, limit=180),
                        "state": _monitor_state(item),
                        "last_status": item.last_status,
                        "last_checked_at": _to_iso(item.last_checked_at),
                        "last_checked_local": _to_local_iso(item.last_checked_at),
                        "check_interval_minutes": item.check_interval_minutes,
                        "active_from_hour": item.active_from_hour,
                        "active_to_hour": item.active_to_hour,
                        "result": _compact_result(item.last_result_json),
                    }
                    for item in active_configs
                ],
                "recent_monitor_events": [
                    {
                        "id": item.id,
                        "monitor_type": item.monitor_type,
                        "point_name": _event_point_label(item),
                        "severity": item.severity,
                        "title": _safe_text(item.title, limit=180),
                        "sent_to_telegram": item.sent_to_telegram,
                        "delivery_channel": (
                            _delivery_channel(user, item)
                            if item.sent_to_telegram and item.telegram_chat_id is not None
                            else None
                        ),
                        "telegram_chat_id": item.telegram_chat_id,
                        "telegram_message_id": item.telegram_message_id,
                        "created_at": _to_iso(item.created_at),
                        "created_local": _to_local_iso(item.created_at),
                        "body_excerpt": _safe_text(item.body, limit=260),
                    }
                    for item in events
                ],
            },
            "what_user_did": {
                "summary": {
                    "visible_telegram_messages": len(visible_messages),
                    "visible_forwarded_messages": len(visible_forwarded),
                    "data_agent_requests": len(requests),
                    "support_messages_from_user": len(user_support_messages),
                    "support_messages_from_bot": len(bot_support_messages),
                },
                "recent_visible_messages": [
                    {
                        "id": item.id,
                        "chat_id": item.chat_id,
                        "telegram_message_id": item.message_id,
                        "observed_at": _to_iso(item.date),
                        "observed_local": _to_local_iso(item.date),
                        "reply_to_message_id": item.reply_to_message_id,
                        "reply_to_from_bot": item.reply_to_from_bot,
                        "is_forwarded": item.is_forwarded,
                        "forward_from_bot": item.forward_from_bot,
                        "forward_origin_type": item.forward_origin_type,
                        "forward_origin_title": _safe_text(item.forward_origin_title, limit=180),
                        "text": _safe_text(item.text, limit=220),
                    }
                    for item in visible_messages[: max(1, args.limit)]
                ],
                "recent_data_agent_requests": [
                    {
                        "id": item.id,
                        "trace_id": item.trace_id,
                        "created_at": _to_iso(item.created_at),
                        "created_local": _to_local_iso(item.created_at),
                        "success": item.success,
                        "duration_ms": item.duration_ms,
                        "text": _safe_text(item.user_message, limit=220),
                    }
                    for item in requests
                ],
                "recent_support_messages_from_user": [
                    {
                        "id": item.id,
                        "created_at": _to_iso(item.created_at),
                        "created_local": _to_local_iso(item.created_at),
                        "telegram_message_id": item.telegram_message_id,
                        "text": _safe_text(item.message_text, limit=220),
                    }
                    for item in user_support_messages
                ],
                "recent_support_replies": [
                    {
                        "id": item.id,
                        "created_at": _to_iso(item.created_at),
                        "created_local": _to_local_iso(item.created_at),
                        "telegram_message_id": item.telegram_message_id,
                        "text": _safe_text(item.message_text, limit=220),
                    }
                    for item in bot_support_messages
                ],
            },
            "observability": {
                "attention_summary": summarize_reaction_matches(attention_matches),
                "attention_matches": [
                    {
                        "event_id": item.delivery.id,
                        "source": item.delivery.source,
                        "title": _safe_text(item.delivery.title, limit=180),
                        "delivery_chat_id": item.delivery.chat_id,
                        "delivery_message_id": item.delivery.telegram_message_id,
                        "sent_local": _to_local_iso(item.delivery.sent_at),
                        "match_type": item.match_type,
                        "latency_minutes": item.latency_minutes,
                        "interaction_id": item.interaction.id if item.interaction else None,
                        "interaction_local": _to_local_iso(item.interaction.observed_at) if item.interaction else None,
                        "interaction_text": _safe_text(item.interaction.text, limit=200) if item.interaction else None,
                        "interaction_forwarded": item.interaction.is_forwarded if item.interaction else None,
                    }
                    for item in attention_matches[: max(1, args.limit)]
                ],
                "limitations": [
                    "Regular Telegram Bot API does not expose true read receipts for outgoing bot messages.",
                    "Forwarding can only be observed when the forwarded message appears in a chat visible to the bot.",
                    "Older sent monitor events may lack telegram_chat_id/message_id if they were created before delivery telemetry was added.",
                ],
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
