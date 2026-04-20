from datetime import datetime, timedelta

from data_agent.attention_monitoring import (
    ObservedDelivery,
    ObservedInteraction,
    match_first_reactions,
    summarize_reaction_matches,
)


def test_match_first_reactions_prefers_direct_reply_to_delivery_message():
    sent_at = datetime(2026, 4, 20, 8, 0, 0)
    delivery = ObservedDelivery(
        id=1,
        chat_id=-1001,
        sent_at=sent_at,
        source="monitor:stoplist",
        telegram_message_id=42,
    )
    interactions = [
        ObservedInteraction(
            id=10,
            chat_id=-1001,
            observed_at=sent_at + timedelta(minutes=7),
            source="group_message",
            reply_to_message_id=None,
        ),
        ObservedInteraction(
            id=11,
            chat_id=-1001,
            observed_at=sent_at + timedelta(minutes=12),
            source="group_message",
            reply_to_message_id=42,
            reply_to_from_bot=True,
        ),
    ]

    matches = match_first_reactions([delivery], interactions)

    assert len(matches) == 1
    assert matches[0].interaction.id == 11
    assert matches[0].match_type == "direct_reply"
    assert matches[0].latency_minutes == 12.0


def test_match_first_reactions_falls_back_to_same_chat_activity():
    sent_at = datetime(2026, 4, 20, 8, 0, 0)
    delivery = ObservedDelivery(id=1, chat_id=-1001, sent_at=sent_at, source="monitor:blanks")
    interaction = ObservedInteraction(
        id=10,
        chat_id=-1001,
        observed_at=sent_at + timedelta(minutes=5),
        source="group_message",
    )

    matches = match_first_reactions([delivery], [interaction])

    assert matches[0].interaction == interaction
    assert matches[0].match_type == "same_chat_activity"
    assert summarize_reaction_matches(matches)["median_latency_minutes"] == 5.0


def test_match_first_reactions_ignores_other_chat_activity():
    sent_at = datetime(2026, 4, 20, 8, 0, 0)
    delivery = ObservedDelivery(id=1, chat_id=-1001, sent_at=sent_at, source="monitor:blanks")
    interaction = ObservedInteraction(
        id=10,
        chat_id=-1002,
        observed_at=sent_at + timedelta(minutes=5),
        source="group_message",
    )

    matches = match_first_reactions([delivery], [interaction])

    assert matches[0].interaction is None
    assert summarize_reaction_matches(matches)["unmatched_deliveries"] == 1
