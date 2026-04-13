import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.orm import Session

from bot.webapp_links import build_taskbridge_webapp_url
from db.models import PendingTask, Task, User
from db.task_retention import visible_tasks

logger = logging.getLogger(__name__)


async def notify_comment_added(
    bot: Bot,
    task_id: int,
    comment_author_id: int,
    comment_text: str,
    db: Session,
) -> None:
    """
    Отправляет уведомления о новом комментарии всем участникам задачи,
    кроме автора комментария.
    """
    try:
        task = visible_tasks(db.query(Task)).filter(Task.id == task_id).first()
        if not task:
            logger.warning("Task %s not found", task_id)
            return

        comment_author = db.query(User).filter(User.id == comment_author_id).first()

        participants = set()
        if task.creator and task.creator.id != comment_author_id:
            participants.add(task.creator)

        for assignee in task.assignees:
            if assignee.id != comment_author_id:
                participants.add(assignee)

        notification = (
            f"💬 <b>Новый комментарий к задаче</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Автор:</b> {comment_author.first_name or comment_author.username}\n"
            f"<b>Комментарий:</b> {comment_text[:200]}{'...' if len(comment_text) > 200 else ''}\n"
        )

        for participant in participants:
            if participant.telegram_id and participant.telegram_id != -1:
                try:
                    webapp_url = build_taskbridge_webapp_url(
                        user_id=participant.id,
                        mode="executor",
                        task_id=task.id,
                    )
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="📱 Открыть задачу",
                                    web_app=WebAppInfo(url=webapp_url),
                                )
                            ]
                        ]
                    )

                    await bot.send_message(
                        chat_id=participant.telegram_id,
                        text=notification,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    logger.info("Comment notification sent to user @%s", participant.username)
                except TelegramForbiddenError:
                    logger.warning("User @%s blocked the bot", participant.username)
                except Exception as exc:
                    logger.error(
                        "Failed to send comment notification to @%s: %s",
                        participant.username,
                        exc,
                    )
    except Exception as exc:
        logger.error("Error in notify_comment_added: %s", exc, exc_info=True)


async def notify_assigned_user(
    bot: Bot,
    task_id: int,
    db: Session,
    assignee: User = None,
) -> bool:
    """Отправляет назначенному исполнителю уведомление о новой задаче."""
    try:
        task = visible_tasks(db.query(Task)).filter(Task.id == task_id).first()
        if not task:
            logger.warning("Task %s not found", task_id)
            return False

        if not assignee:
            if not task.assignees:
                logger.warning("Task %s has no assignees", task_id)
                return False
            assignee = task.assignees[0]

        if assignee.telegram_id in (None, -1):
            logger.warning("User @%s has not started the bot yet", assignee.username)
            return False

        notification = (
            f"📌 <b>Вам назначили новую задачу</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )
        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"
        if len(task.assignees) > 1:
            assignees_str = ", ".join(f"@{a.username}" for a in task.assignees if a.username)
            if assignees_str:
                notification += f"<b>Исполнители:</b> {assignees_str}\n"
        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
        notification += f"<b>Приоритет:</b> {task.priority}\n"
        notification += f"<b>Статус:</b> {task.status}"

        notification = (
            "📌 <b>Новая задача</b>\n\n"
            f"<b>Что сделать:</b> {task.title}\n"
        )
        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"
        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
        notification += f"<b>Приоритет:</b> {task.priority}\n"

        webapp_url = build_taskbridge_webapp_url(
            user_id=assignee.id,
            mode="executor",
            task_id=task.id,
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton(text="▶️ Начать выполнение", callback_data=f"task_start:{task.id}")],
                [InlineKeyboardButton(text="✅ Завершить", callback_data=f"task_complete:{task.id}")],
            ]
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton(text="▶️ Взять в работу", callback_data=f"task_start:{task.id}")],
                [InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"task_complete:{task.id}")],
            ]
        )

        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=notification,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        logger.info("Notification sent to user @%s (ID: %s)", assignee.username, assignee.telegram_id)
        return True
    except TelegramForbiddenError:
        logger.warning("User blocked the bot or has not started it")
        return False
    except Exception as exc:
        logger.error("Failed to send notification: %s", exc, exc_info=True)
        return False


def build_bot_start_url(bot_username: str, start_param: str = "taskbridge") -> str:
    return f"https://t.me/{bot_username}?start={start_param}"


def format_user_mention(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return "Пользователь"


async def send_assignee_start_prompt(
    bot: Bot,
    chat_id: int,
    assignee: User,
    task_title: str,
) -> None:
    bot_info = await bot.get_me()
    start_url = build_bot_start_url(bot_info.username)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть чат с ботом", url=start_url)]]
    )
    mention = format_user_mention(assignee)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{mention}, вам назначили задачу <b>{task_title}</b>.\n\n"
            "Пожалуйста, перейдите в чат со мной и нажмите Start, чтобы получать задачи и работать с ними."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def send_creator_start_prompt(bot: Bot, source_message: Message) -> None:
    bot_info = await bot.get_me()
    start_url = build_bot_start_url(bot_info.username)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть чат с ботом", url=start_url)]]
    )
    mention = (
        f"@{source_message.from_user.username}"
        if source_message.from_user.username
        else source_message.from_user.first_name
    )
    await source_message.answer(
        f"{mention}, чтобы подтвердить задачу, перейдите в личный чат со мной и нажмите Start.",
        reply_markup=keyboard,
    )


async def send_private_assignee_selection(
    bot: Bot,
    creator: User,
    pending_task: PendingTask,
    members: list[dict],
) -> bool:
    if creator.telegram_id in (None, -1):
        return False

    ask_text = (
        f"👤 <b>Выберите исполнителя</b>\n\n"
        f"<b>Задача:</b> {pending_task.title}\n"
    )
    if pending_task.description:
        ask_text += f"<b>Описание:</b> {pending_task.description}\n"
    if pending_task.due_date:
        ask_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
    ask_text += "\nКому назначить эту задачу?"

    buttons = []
    row = []
    for member in members:
        display_name = member.get("first_name") or member.get("username") or f"User {member['id']}"
        row.append(
            InlineKeyboardButton(
                text=display_name[:24],
                callback_data=f"assign_user:{pending_task.id}:{member['id']}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append(
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_task:{pending_task.id}")]
    )

    sent = await bot.send_message(
        chat_id=creator.telegram_id,
        text=ask_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    pending_task.telegram_message_id = sent.message_id
    return True
