from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from db.models import Message as MessageModel


def get_recent_chat_context(
    db: Session,
    chat_id: int,
    current_message_db_id: int,
    current_message_date: Optional[datetime] = None,
    current_user_id: Optional[int] = None,
    limit: int = 3,
    max_age_minutes: int = 15,
) -> List[dict]:
    """Return recent chat messages for context-aware task extraction."""
    query = (
        db.query(MessageModel)
        .filter(
            MessageModel.chat_id == chat_id,
            MessageModel.id < current_message_db_id,
            MessageModel.text.isnot(None),
            MessageModel.has_task.is_(False),
        )
    )

    if current_message_date is not None:
        min_context_date = current_message_date - timedelta(minutes=max_age_minutes)
        query = query.filter(
            MessageModel.date <= current_message_date,
            MessageModel.date >= min_context_date,
        )

    if current_user_id is not None:
        query = query.filter(MessageModel.user_id == current_user_id)

    recent_messages = (
        query.order_by(MessageModel.date.desc(), MessageModel.id.desc()).limit(limit).all()
    )

    context_messages: List[dict] = []
    for item in reversed(recent_messages):
        sender_name = "unknown"
        if item.user:
            sender_name = (
                item.user.first_name
                or (f"@{item.user.username}" if item.user.username else None)
                or f"user_{item.user_id}"
            )

        context_messages.append(
            {
                "sender": sender_name,
                "date": item.date.strftime("%Y-%m-%d %H:%M:%S") if item.date else "",
                "text": item.text or "",
            }
        )

    return context_messages
