from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median


@dataclass(frozen=True)
class ObservedDelivery:
    id: int
    chat_id: int
    sent_at: datetime
    source: str
    title: str | None = None
    telegram_message_id: int | None = None


@dataclass(frozen=True)
class ObservedInteraction:
    id: int
    chat_id: int
    observed_at: datetime
    source: str
    text: str | None = None
    reply_to_message_id: int | None = None
    reply_to_from_bot: bool | None = None
    is_forwarded: bool = False
    forward_origin_type: str | None = None
    forward_origin_title: str | None = None
    forward_from_bot: bool | None = None


@dataclass(frozen=True)
class ReactionMatch:
    delivery: ObservedDelivery
    interaction: ObservedInteraction | None
    match_type: str | None
    latency_seconds: int | None

    @property
    def latency_minutes(self) -> float | None:
        if self.latency_seconds is None:
            return None
        return round(self.latency_seconds / 60, 1)


def match_first_reactions(
    deliveries: list[ObservedDelivery],
    interactions: list[ObservedInteraction],
    *,
    max_latency_hours: int = 72,
) -> list[ReactionMatch]:
    """Match outgoing bot deliveries to the first visible user action after them.

    This is intentionally not a read receipt. Telegram Bot API does not expose
    regular "seen" events, so we measure the first action the bot can observe.
    """

    sorted_interactions = sorted(interactions, key=lambda item: item.observed_at)
    window = timedelta(hours=max(1, max_latency_hours))
    matches: list[ReactionMatch] = []

    for delivery in sorted(deliveries, key=lambda item: item.sent_at):
        deadline = delivery.sent_at + window
        candidates = [
            item
            for item in sorted_interactions
            if item.chat_id == delivery.chat_id
            and delivery.sent_at <= item.observed_at <= deadline
        ]
        if not candidates:
            matches.append(ReactionMatch(delivery=delivery, interaction=None, match_type=None, latency_seconds=None))
            continue

        direct_reply = None
        if delivery.telegram_message_id is not None:
            direct_reply = next(
                (
                    item
                    for item in candidates
                    if item.reply_to_message_id == delivery.telegram_message_id
                ),
                None,
            )
        if direct_reply:
            matched = direct_reply
            match_type = "direct_reply"
        else:
            reply_to_bot = next((item for item in candidates if item.reply_to_from_bot is True), None)
            if reply_to_bot:
                matched = reply_to_bot
                match_type = "reply_to_bot"
            else:
                matched = candidates[0]
                match_type = "same_chat_activity"

        latency = int((matched.observed_at - delivery.sent_at).total_seconds())
        matches.append(
            ReactionMatch(
                delivery=delivery,
                interaction=matched,
                match_type=match_type,
                latency_seconds=max(0, latency),
            )
        )

    return matches


def summarize_reaction_matches(matches: list[ReactionMatch]) -> dict:
    matched = [item for item in matches if item.interaction is not None and item.latency_seconds is not None]
    latencies = [item.latency_minutes for item in matched if item.latency_minutes is not None]
    match_type_counts: dict[str, int] = {}
    for item in matched:
        match_type = item.match_type or "unknown"
        match_type_counts[match_type] = match_type_counts.get(match_type, 0) + 1

    summary = {
        "deliveries": len(matches),
        "matched_visible_reactions": len(matched),
        "unmatched_deliveries": len(matches) - len(matched),
        "match_type_counts": dict(sorted(match_type_counts.items())),
    }
    if latencies:
        summary.update(
            {
                "min_latency_minutes": min(latencies),
                "median_latency_minutes": round(float(median(latencies)), 1),
                "max_latency_minutes": max(latencies),
            }
        )
    return summary
