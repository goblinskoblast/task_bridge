"""
Модуль для отправки уведомлений через Telegram бота.
Используется из FastAPI для асинхронных уведомлений.
"""
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.orm import Session

from db.models import Task, User
from config import WEB_APP_DOMAIN, BOT_TOKEN

logger = logging.getLogger(__name__)

# Глобальный экземпляр бота для уведомлений
_bot_instance: Optional[Bot] = None


def get_notification_bot() -> Bot:
    """Получить экземпляр бота для отправки уведомлений"""
    global _bot_instance
    if _bot_instance is None:
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        _bot_instance = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return _bot_instance


async def notify_comment_added(task_id: int, comment_author_id: int, comment_text: str, db: Session) -> None:
    """
    Отправляет уведомления о новом комментарии всем участникам задачи
    (создателю и исполнителям), кроме автора комментария.
    """
    try:
        bot = get_notification_bot()

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        comment_author = db.query(User).filter(User.id == comment_author_id).first()
        if not comment_author:
            logger.warning(f"Comment author {comment_author_id} not found")
            return

        # Собираем всех участников задачи (создатель + исполнители)
        participants = set()

        # Добавляем создателя задачи
        if task.creator and task.creator.id != comment_author_id:
            participants.add(task.creator)

        # Добавляем всех исполнителей
        for assignee in task.assignees:
            if assignee.id != comment_author_id:
                participants.add(assignee)

        # Формируем уведомление
        author_name = comment_author.first_name or comment_author.username or "Пользователь"
        notification = (
            f"💬 <b>Новый комментарий к задаче</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Автор:</b> {author_name}\n"
            f"<b>Комментарий:</b> {comment_text[:200]}{'...' if len(comment_text) > 200 else ''}\n"
        )

        # Отправляем уведомления всем участникам
        for participant in participants:
            if participant.telegram_id and participant.telegram_id != -1:
                try:
                    webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={participant.id}&task_id={task.id}"
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📱 Открыть задачу",
                                web_app=WebAppInfo(url=webapp_url)
                            )
                        ]
                    ])

                    await bot.send_message(
                        chat_id=participant.telegram_id,
                        text=notification,
                        reply_markup=keyboard
                    )
                    logger.info(f"Comment notification sent to user @{participant.username} (ID: {participant.telegram_id})")
                except TelegramForbiddenError:
                    logger.warning(f"User @{participant.username} blocked the bot")
                except Exception as e:
                    logger.error(f"Failed to send comment notification to @{participant.username}: {e}")
    except Exception as e:
        logger.error(f"Error in notify_comment_added: {e}", exc_info=True)


async def notify_status_changed(
    task_id: int,
    old_status: str,
    new_status: str,
    changed_by_user_id: int,
    db: Session
) -> None:
    """
    Отправляет уведомления об изменении статуса задачи всем участникам
    (создателю и исполнителям), кроме того кто изменил статус.

    Args:
        task_id: ID задачи
        old_status: Предыдущий статус
        new_status: Новый статус
        changed_by_user_id: ID пользователя, который изменил статус
        db: Сессия базы данных
    """
    try:
        bot = get_notification_bot()

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        changed_by = db.query(User).filter(User.id == changed_by_user_id).first()
        if not changed_by:
            logger.warning(f"User {changed_by_user_id} not found")
            return

        # Словарь для красивого отображения статусов
        status_names = {
            "pending": "⏳ Ожидание",
            "in_progress": "🔄 В работе",
            "completed": "✅ Завершена",
            "cancelled": "❌ Отменена"
        }

        # Собираем всех участников задачи (создатель + исполнители)
        participants = set()

        # Добавляем создателя
        if task.creator:
            participants.add(task.creator)

        # Добавляем всех исполнителей
        for assignee in task.assignees:
            participants.add(assignee)

        # Убираем того, кто изменил статус
        participants = {p for p in participants if p.id != changed_by_user_id}

        if not participants:
            logger.info(f"No participants to notify for task {task_id}")
            return

        # Формируем текст уведомления
        changed_by_name = changed_by.first_name or changed_by.username or "Пользователь"
        old_status_text = status_names.get(old_status, old_status)
        new_status_text = status_names.get(new_status, new_status)

        notification = (
            f"🔔 <b>Изменение статуса задачи</b>\n\n"
            f"<b>{task.title}</b>\n\n"
            f"Статус изменен: {old_status_text} → {new_status_text}\n"
            f"Изменил: {changed_by_name}"
        )

        # Отправляем уведомления всем участникам
        for participant in participants:
            if participant.telegram_id and participant.telegram_id != -1:
                try:
                    webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={participant.id}&task_id={task.id}"
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📱 Открыть задачу",
                                web_app=WebAppInfo(url=webapp_url)
                            )
                        ]
                    ])

                    await bot.send_message(
                        chat_id=participant.telegram_id,
                        text=notification,
                        reply_markup=keyboard
                    )
                    logger.info(
                        f"Status change notification sent to user @{participant.username} "
                        f"(ID: {participant.telegram_id}) for task {task_id}"
                    )
                except TelegramForbiddenError:
                    logger.warning(f"User @{participant.username} blocked the bot")
                except Exception as e:
                    logger.error(f"Failed to send status notification to @{participant.username}: {e}")
    except Exception as e:
        logger.error(f"Error in notify_status_changed: {e}", exc_info=True)
