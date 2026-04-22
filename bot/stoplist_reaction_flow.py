from __future__ import annotations

import logging
from datetime import datetime

from aiogram.types import Message

from data_agent.stoplist_reactions import apply_stoplist_reaction

logger = logging.getLogger(__name__)


async def maybe_handle_stoplist_reaction(
    message: Message,
    *,
    db,
    telegram_user_id: int,
) -> bool:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", telegram_user_id)
    result = apply_stoplist_reaction(
        db,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        text=getattr(message, "text", None),
        observed_at=getattr(message, "date", None) or datetime.utcnow(),
        message_id=getattr(message, "message_id", None),
        reply_to_message_id=getattr(getattr(message, "reply_to_message", None), "message_id", None),
        reply_to_from_bot=(
            getattr(getattr(getattr(message, "reply_to_message", None), "from_user", None), "is_bot", None)
        ),
    )
    if result is None:
        return False

    logger.info(
        "Stoplist reaction handled chat_id=%s telegram_user_id=%s matched=%s status=%s incident_id=%s matched_by=%s",
        chat_id,
        telegram_user_id,
        result.matched,
        result.manager_status,
        result.incident_id,
        result.matched_by,
    )
    await message.answer(result.response_text)
    return True
