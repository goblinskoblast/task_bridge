import logging
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from aiogram import Bot, Router, F
from aiogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup,
    CallbackQuery, PhotoSize, Document, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import TASK_KEYWORDS, MINI_APP_URL, HOST, PORT
from db.models import User, Message as MessageModel, Task, Category, PendingTask, TaskFile, Chat
from db.database import get_db_session
from db.task_retention import actionable_tasks, visible_tasks
from bot.ai_extractor import analyze_message, telegram_message_requires_context
from bot.task_file_binding import extract_task_reference, resolve_task_for_file_upload
from bot.webapp_links import build_taskbridge_webapp_url
from bot.task_notifications import (
    format_user_mention,
    notify_assigned_user,
    send_assignee_start_prompt,
    send_creator_start_prompt,
    send_private_assignee_selection,
)
from bot.telegram_context import get_recent_chat_context

logger = logging.getLogger(__name__)

router = Router()

PANEL_BUTTON_TEXT = "📱 Панель задач"
AGENT_MAIN_BUTTON_TEXT = "🤖 Агент"
QUICK_REPORTS_BUTTON_TEXT = "⚡ Быстрые отчёты"
MONITORS_BUTTON_TEXT = "📡 Мониторы"
SUPPORT_BUTTON_TEXT = "💬 Поддержка"
HELP_BUTTON_TEXT = "❓ Помощь"


def init_default_categories(db: Session):
    """Инициализация стандартных категорий задач."""
    default_categories = [
        {
            "name": "Разработка",
            "description": "Задачи по разработке и программированию",
            "keywords": ["код", "программ", "разработ", "git", "commit", "repo", "repository", "bug", "issue", "pull request", "merge", "deploy", "dev", "development", "backend", "frontend", "api", "endpoint", "database", "sql", "query"]
        },
        {
            "name": "Дизайн",
            "description": "Задачи по дизайну и визуализации",
            "keywords": ["дизайн", "макет", "ui", "ux", "рисун", "эскиз", "mockup", "wireframe", "prototype", "figma", "sketch", "illustration", "graphics", "visual", "interface"]
        },
        {
            "name": "Маркетинг",
            "description": "Маркетинговые задачи и SMM",
            "keywords": ["маркетинг", "реклам", "пост", "smm", "контент", "соцсети", "social", "campaign", "promotion", "advertising", "conversion", "seo", "crm"]
        },
        {
            "name": "Аналитика",
            "description": "Аналитические и отчётные задачи",
            "keywords": ["аналитик", "отчёт", "статистик", "metric", "dashboard", "kpi", "analytics", "data", "metric", "report", "analysis"]
        },
        {
            "name": "Встречи",
            "description": "Встречи и переговоры",
            "keywords": ["встреч", "собрание", "звонок", "онлайн", "meeting", "call", "conference", "presentation"]
        },
        {
            "name": "uncategorized",
            "description": "Задачи без определённой категории",
            "keywords": []
        }
    ]

    for cat_data in default_categories:
        category = db.query(Category).filter(Category.name == cat_data["name"]).first()
        if not category:
            category = Category(
                name=cat_data["name"],
                description=cat_data["description"],
                keywords=cat_data["keywords"]
            )
            db.add(category)

    db.commit()


def classify_task(text: str, db: Session) -> Optional[int]:
    
    if not text:
        category = db.query(Category).filter(Category.name == "uncategorized").first()
        if not category:
            init_default_categories(db)
            category = db.query(Category).filter(Category.name == "uncategorized").first()
        return category.id

    text_lower = text.lower()
    categories = db.query(Category).filter(Category.keywords.isnot(None)).all()

    for category in categories:
        if category.keywords:
            if any(keyword in text_lower for keyword in category.keywords):
                return category.id

    category = db.query(Category).filter(Category.name == "uncategorized").first()
    if not category:
        init_default_categories(db)
        category = db.query(Category).filter(Category.name == "uncategorized").first()
    return category.id


async def get_or_create_user(bot: Bot, telegram_id: int, username: str = None,
                              first_name: str = None, last_name: str = None,
                              is_bot: bool = False, db: Session = None) -> User:
    """Получает пользователя из БД или создаёт нового."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_bot=is_bot
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    updated = False
    if username and user.username != username:
        user.username = username
        updated = True
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        updated = True
    if last_name and user.last_name != last_name:
        user.last_name = last_name
        updated = True
    if user.is_bot != is_bot:
        user.is_bot = is_bot
        updated = True
    if updated:
        db.commit()
        db.refresh(user)

    return user


def _allocate_placeholder_telegram_id(db: Session) -> int:
    min_negative = db.query(func.min(User.telegram_id)).filter(User.telegram_id < 0).scalar()
    if min_negative is None:
        return -1
    return int(min_negative) - 1


async def get_or_create_user_by_username(db: Session, username: str) -> User:
    if username.startswith("tgid:"):
        telegram_id = int(username.split(":", 1)[1])
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            return user

        user = User(
            telegram_id=telegram_id,
            username=None,
            first_name=f"user_{telegram_id}",
            is_bot=False
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing_user = db.query(User).filter(User.telegram_id == telegram_id).first()
            if existing_user:
                return existing_user
            raise

        db.refresh(user)
        logger.info(f"Created user placeholder by telegram id {telegram_id} (ID: {user.id})")
        return user

    normalized_username = str(username or "").strip().lstrip("@")
    user = db.query(User).filter(User.username == normalized_username).first()
    if user:
        return user

    for _ in range(3):
        placeholder_telegram_id = _allocate_placeholder_telegram_id(db)
        user = User(
            telegram_id=placeholder_telegram_id,
            username=normalized_username,
            first_name=f"@{normalized_username}",
            is_bot=False
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
            logger.info(
                f"Created temporary user @{normalized_username} with placeholder telegram_id={placeholder_telegram_id} (ID: {user.id})"
            )
            return user
        except IntegrityError:
            db.rollback()
            existing_user = db.query(User).filter(User.username == normalized_username).first()
            if existing_user:
                return existing_user

    raise RuntimeError(f"Failed to allocate placeholder user for @{normalized_username}")


async def get_or_create_chat(chat_id: int, chat_type: str, title: str = None,
                              username: str = None, db: Session = None) -> Chat:
    """Получает чат из БД или создаёт новый."""
    chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()

    if not chat:
        chat = Chat(
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            username=username,
            is_active=True
        )
        db.add(chat)
        db.commit()
        db.refresh(chat)
        logger.info(f"Registered new chat: {chat_id} ({chat_type}) - {title}")
    else:
        # Обновляем информацию о чате, если она изменилась
        updated = False
        if chat.title != title and title:
            chat.title = title
            updated = True
        if chat.username != username and username:
            chat.username = username
            updated = True
        if not chat.is_active:
            chat.is_active = True
            updated = True

        if updated:
            db.commit()
            db.refresh(chat)
            logger.info(f"Updated chat info: {chat_id}")

    return chat


def _extract_reply_assignee_hint(message: Message) -> Optional[Dict[str, Any]]:
    reply_message = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply_message, "from_user", None)
    message_user = getattr(message, "from_user", None)

    if not reply_user or reply_user.is_bot:
        return None
    if message_user and reply_user.id == message_user.id:
        return None

    return {
        "token": reply_user.username or f"tgid:{reply_user.id}",
        "telegram_id": reply_user.id,
        "username": reply_user.username,
        "first_name": reply_user.first_name,
        "last_name": getattr(reply_user, "last_name", None),
        "is_bot": reply_user.is_bot,
    }


def _resolve_assignee_usernames(
    task_data: Optional[Dict[str, Any]],
    reply_assignee_hint: Optional[Dict[str, Any]] = None,
) -> List[str]:
    task_data = task_data or {}
    assignee_usernames = task_data.get("assignee_usernames", []) or []
    if not assignee_usernames and task_data.get("assignee_username"):
        assignee_usernames = [task_data.get("assignee_username")]

    normalized: List[str] = []
    for raw_token in assignee_usernames:
        token = str(raw_token or "").strip().lstrip("@")
        if token and token not in normalized:
            normalized.append(token)

    if not normalized and reply_assignee_hint:
        normalized.append(reply_assignee_hint["token"])

    return normalized


def _format_assignee_label(db: Session, assignee_token: str) -> str:
    token = str(assignee_token or "").strip()
    if not token:
        return "Исполнитель"

    if token.startswith("tgid:"):
        try:
            telegram_id = int(token.split(":", 1)[1])
        except (IndexError, ValueError):
            return "Пользователь Telegram"

        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            return format_user_mention(user)
        return "Пользователь Telegram"

    user = db.query(User).filter(User.username == token).first()
    if user:
        return format_user_mention(user)

    if re.search(r"[А-Яа-яЁё ]", token):
        return token

    return f"@{token}"


def _build_main_reply_keyboard(webapp_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PANEL_BUTTON_TEXT, web_app=WebAppInfo(url=webapp_url))],
            [KeyboardButton(text=AGENT_MAIN_BUTTON_TEXT), KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
            [KeyboardButton(text=HELP_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="Напишите задачу или выберите действие ниже",
    )


def _build_welcome_message(is_first_auth: bool, pending_count: int) -> str:
    if pending_count:
        intro = (
            f"👋 <b>С возвращением</b>\n\n"
            f"Сейчас у вас <b>{pending_count}</b> активных задач."
        )
        if is_first_auth:
            intro = (
                f"👋 <b>Добро пожаловать в TaskBridge</b>\n\n"
                f"Для вас уже найдено <b>{pending_count}</b> активных задач."
            )
    else:
        intro = (
            "👋 <b>TaskBridge готов к работе</b>\n\n"
            "Я помогу собирать задачи из чатов и быстро открывать отчёты через агента."
        )

    return (
        f"{intro}\n\n"
        "Что можно сделать прямо сейчас:\n"
        f"• {PANEL_BUTTON_TEXT.lower()}\n"
        "• запустить агента для отчётов\n"
        "• открыть поддержку, если нужна помощь\n"
        "• сохранить точки для быстрых отчётов через /addpoint и /points"
    )


def _build_pending_task_confirmation_text(db: Session, pending_task: PendingTask) -> str:
    lines = [
        "📋 <b>Подтвердите задачу</b>",
        "",
        f"<b>Что сделать:</b> {pending_task.title}",
    ]

    if pending_task.description and pending_task.description != pending_task.title:
        lines.append(f"<b>Описание:</b> {pending_task.description}")

    assignee_tokens = pending_task.assignee_usernames or []
    if not assignee_tokens and pending_task.assignee_username:
        assignee_tokens = [pending_task.assignee_username]
    if assignee_tokens:
        assignee_labels = [_format_assignee_label(db, token) for token in assignee_tokens]
        label = "Исполнитель" if len(assignee_labels) == 1 else "Исполнители"
        lines.append(f"<b>{label}:</b> {', '.join(assignee_labels)}")

    if pending_task.due_date:
        lines.append(f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}")

    lines.append(f"<b>Приоритет:</b> {pending_task.priority}")
    lines.extend(["", "Подтвердить создание задачи?"])
    return "\n".join(lines)


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    db = get_db_session()
    try:
        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db,
        )

        is_first_auth = user.telegram_id == -1 or user.telegram_id != message.from_user.id
        if is_first_auth:
            user.telegram_id = message.from_user.id
            db.commit()
            logger.info("Updated telegram_id for user @%s (ID: %s)", user.username, user.id)

        pending_tasks = actionable_tasks(db.query(Task)).join(Task.assignees).filter(
            User.id == user.id,
        ).all()

        if pending_tasks:
            for task in pending_tasks:
                task_webapp_url = build_taskbridge_webapp_url(
                    user_id=user.id,
                    mode="executor",
                    task_id=task.id,
                )
                task_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(
                            text="📱 Открыть задачу",
                            web_app=WebAppInfo(url=task_webapp_url),
                        )
                    ]]
                )
                notification = f"""📌 <b>У вас есть активная задача</b>

<b>{task.title}</b>
Статус: {task.status}
Приоритет: {task.priority}
"""
                if task.due_date:
                    notification += f"Срок: {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
                await message.answer(notification, reply_markup=task_keyboard, parse_mode="HTML")

        webapp_url = build_taskbridge_webapp_url(user_id=user.id, mode="executor")
        reply_keyboard = _build_main_reply_keyboard(webapp_url)
        welcome_message = _build_welcome_message(is_first_auth, len(pending_tasks))
        await message.answer(welcome_message, reply_markup=reply_keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /start command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    """Handle /panel command."""
    db = get_db_session()

    try:
        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db
        )

        webapp_url = build_taskbridge_webapp_url(user_id=user.id, mode="executor")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📱 Открыть панель задач",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]]
        )
        await message.answer(
            """📱 <b>Панель задач</b>

Откройте мини-приложение, чтобы посмотреть задачи, статусы и файлы.""",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Error in /panel command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Show a short help message."""
    modern_help_text = """❓ <b>Коротко о возможностях TaskBridge</b>

<b>Быстрые действия</b>
• /start — главное меню
• /panel — открыть панель задач
• /agent — открыть меню агента
• /support — написать в поддержку

<b>Точки и отчёты</b>
• /addpoint — сохранить точку
• /points — посмотреть сохранённые точки
• /delpoint ID — убрать точку из списка

<b>Быстрые отчёты</b>
• /reviews точка за сутки
• /stoplist точка
• /blanks точка текущий бланк
• /monitors — список мониторингов

<b>Как это работает</b>
1. Напишите задачу в рабочем чате.
2. Бот пришлёт подтверждение в личку.
3. После подтверждения задача появится у исполнителя и в панели.
4. Для отчётов по точкам можно один раз сохранить адрес и дальше выбирать его из списка."""
    await message.answer(modern_help_text, parse_mode="HTML")


@router.message(F.chat.type == "private", F.text == HELP_BUTTON_TEXT)
async def help_from_button(message: Message) -> None:
    await cmd_help(message)


@router.callback_query(F.data.startswith("task_start:"))
async def handle_task_start(callback: CallbackQuery):
    """Обработчик начала выполнения задачи."""
    db = get_db_session()

    try:
        task_id = int(callback.data.split(":")[1])
        task = visible_tasks(db.query(Task)).filter(Task.id == task_id).first()

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if task.status == "completed":
            await callback.answer("Задача уже выполнена", show_alert=True)
            return

        
        task.status = "in_progress"
        db.commit()

        
        notification = (
            f"▶️ <b>Задача в процессе выполнения</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>Приоритет:</b> {task.priority}\n"
        notification += f"<b>Статус:</b> в процессе\n"
        notification += f"\n📎 Можете отправить фото или файлы как отчёт"

        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено",
                    callback_data=f"task_complete:{task.id}"
                )
            ]
        ])

        await callback.message.edit_text(notification, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("Статус изменён на 'в процессе' ✅")

    except Exception as e:
        logger.error(f"Error starting task: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("assign_user:"))
async def handle_assign_user(callback: CallbackQuery):
    """Выбор исполнителя для pending-задачи из личного сообщения постановщику."""
    db = get_db_session()
    try:
        _, pending_task_id, selected_telegram_id = callback.data.split(":")
        pending_task = db.query(PendingTask).filter(PendingTask.id == int(pending_task_id)).first()
        if not pending_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        if not creator or creator.telegram_id != callback.from_user.id:
            await callback.answer("Вы не можете выбирать исполнителя для этой задачи", show_alert=True)
            return

        selected_telegram_id = int(selected_telegram_id)
        assignee = db.query(User).filter(User.telegram_id == selected_telegram_id).first()
        if not assignee:
            member = await callback.bot.get_chat_member(pending_task.chat_id, selected_telegram_id)
            assignee = User(
                telegram_id=selected_telegram_id,
                username=member.user.username,
                first_name=member.user.first_name,
                last_name=member.user.last_name,
                is_bot=member.user.is_bot,
            )
            db.add(assignee)
            db.commit()
            db.refresh(assignee)

        assignee_token = assignee.username if assignee.username else f"tgid:{assignee.telegram_id}"
        pending_task.assignee_usernames = [assignee_token]
        pending_task.assignee_username = assignee_token
        db.commit()

        assignee_name = format_user_mention(assignee)
        confirmation_text = (
            f"📋 <b>Подтвердите задачу</b>\n\n"
            f"<b>Задача:</b> {pending_task.title}\n"
            f"<b>Исполнитель:</b> {assignee_name}\n"
        )
        if pending_task.description:
            confirmation_text += f"<b>Описание:</b> {pending_task.description}\n"
        if pending_task.due_date:
            confirmation_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
        confirmation_text += f"<b>Приоритет:</b> {pending_task.priority}\n\nПодтвердить создание задачи?"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_task:{pending_task.id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_task:{pending_task.id}")]])
        confirmation_text = _build_pending_task_confirmation_text(db, pending_task)
        await callback.message.edit_text(confirmation_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("Исполнитель выбран")
    except TelegramForbiddenError:
        await callback.answer("Исполнитель ещё не запускал бота. Пусть сначала нажмёт /start", show_alert=True)
    except Exception as e:
        logger.error(f"Error in assign_user callback: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("confirm_task:"))
async def handle_confirm_task(callback: CallbackQuery):
    """Подтверждает pending-задачу и создаёт обычную задачу."""
    db = get_db_session()
    try:
        pending_task_id = int(callback.data.split(":")[1])
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()
        if not pending_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return
        if pending_task.status != "pending":
            await callback.answer("Задача уже обработана", show_alert=True)
            return

        assignee_usernames = pending_task.assignee_usernames or []
        if not assignee_usernames and pending_task.assignee_username:
            assignee_usernames = [pending_task.assignee_username]

        category_id = classify_task(pending_task.description or pending_task.title, db)
        due_date = pending_task.due_date or (datetime.now() + timedelta(hours=24))

        task = Task(
            message_id=pending_task.message_id,
            category_id=category_id,
            created_by=pending_task.created_by_id,
            title=pending_task.title,
            description=pending_task.description,
            status="pending",
            priority=pending_task.priority,
            due_date=due_date,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        if assignee_usernames:
            for username in assignee_usernames:
                assignee = await get_or_create_user_by_username(db, username)
                task.assignees.append(assignee)
            db.commit()

        from bot.calendar_sync import sync_task_to_connected_calendars
        sync_task_to_connected_calendars(task, db)

        pending_task.status = "confirmed"
        db.commit()

        if task.assignees:
            for assignee in task.assignees:
                notification_sent = await notify_assigned_user(callback.bot, task.id, db, assignee=assignee)
                if not notification_sent:
                    try:
                        await send_assignee_start_prompt(callback.bot, pending_task.chat_id, assignee, task.title)
                    except Exception as e:
                        logger.error(f"Failed to send start prompt for assignee: {e}", exc_info=True)

        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        webapp_url = build_taskbridge_webapp_url(user_id=pending_task.created_by_id, task_id=task.id)
        if creator:
            webapp_url = build_taskbridge_webapp_url(
                user_id=creator.id,
                mode="manager",
                task_id=task.id,
            )
        manager_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))]])

        confirmation_msg = (
            f"✅ <b>Задача подтверждена и создана</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )
        if task.assignees:
            if len(task.assignees) == 1:
                confirmation_msg += f"<b>Исполнитель:</b> {format_user_mention(task.assignees[0])}\n"
            else:
                confirmation_msg += f"<b>Исполнители:</b> {', '.join(format_user_mention(a) for a in task.assignees)}\n"
        else:
            confirmation_msg += "<b>Исполнитель:</b> не выбран\n"
        confirmation_msg += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'не задан'}\n"
        confirmation_msg += f"<b>Приоритет:</b> {task.priority}"

        await callback.message.edit_text(confirmation_msg, reply_markup=manager_keyboard, parse_mode="HTML")
        await callback.answer("Задача создана")
    except Exception as e:
        logger.error(f"Error confirming task: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("reject_task:"))
async def handle_reject_task(callback: CallbackQuery):
    """Обработчик отклонения задачи."""
    db = get_db_session()

    try:
        pending_task_id = int(callback.data.split(":")[1])
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()

        if not pending_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if pending_task.status != "pending":
            await callback.answer("Задача уже обработана", show_alert=True)
            return

        pending_task.status = "rejected"
        db.commit()

        await callback.message.edit_text(
            f"❌ <b>Задача отклонена</b>\n\n"
            f"Задача: {pending_task.title}",
            parse_mode="HTML"
        )

        await callback.answer("Задача отклонена")

    except Exception as e:
        logger.error(f"Error rejecting task: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("task_complete:"))
async def handle_task_complete(callback: CallbackQuery):
    """Обработчик отметки задачи как выполненной."""
    db = get_db_session()

    try:
        task_id = int(callback.data.split(":")[1])
        task = visible_tasks(db.query(Task)).filter(Task.id == task_id).first()

        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        if task.status == "completed":
            await callback.answer("Задача уже выполнена", show_alert=True)
            return

        task.status = "completed"
        db.commit()

        await callback.message.edit_text(
            f"✅ <b>Задача выполнена!</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Завершена:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="HTML"
        )

        await callback.answer("Отлично! Задача отмечена как выполненная ✅")

    except Exception as e:
        logger.error(f"Error completing task: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message(message: Message):
    """Обрабатывает сообщения в группе и выносит подтверждение найденной задачи в личку."""
    db = get_db_session()
    try:
        if message.from_user.is_bot or not message.text:
            return

        await get_or_create_chat(
            chat_id=message.chat.id,
            chat_type=message.chat.type,
            title=message.chat.title,
            username=message.chat.username,
            db=db,
        )
        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db,
        )
        reply_assignee_hint = _extract_reply_assignee_hint(message)
        if reply_assignee_hint:
            await get_or_create_user(
                bot=message.bot,
                telegram_id=reply_assignee_hint["telegram_id"],
                username=reply_assignee_hint["username"],
                first_name=reply_assignee_hint["first_name"],
                last_name=reply_assignee_hint["last_name"],
                is_bot=reply_assignee_hint["is_bot"],
                db=db,
            )

        message_obj = MessageModel(
            message_id=message.message_id,
            chat_id=message.chat.id,
            user_id=user.id,
            text=message.text,
            date=message.date,
            has_task=False,
        )
        db.add(message_obj)
        db.commit()
        db.refresh(message_obj)

        context_messages: List[dict] = []
        if telegram_message_requires_context(message.text):
            context_messages = get_recent_chat_context(
                db=db,
                chat_id=message.chat.id,
                current_message_db_id=message_obj.id,
                current_message_date=message.date,
                current_user_id=user.id,
            )
            logger.info(
                "Analyzing message with %s bounded context items: %s...",
                len(context_messages),
                message.text[:50],
            )
        else:
            logger.info("Analyzing self-contained message without context: %s...", message.text[:50])

        ai_result = await analyze_message(
            message.text,
            use_ai=True,
            context_messages=context_messages or None,
        )
        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in message")
            return

        message_obj.has_task = True
        db.commit()
        task_data = ai_result.get("task", {})
        logger.info("Task data from AI: %s", task_data)

        assignee_usernames = _resolve_assignee_usernames(task_data, reply_assignee_hint=reply_assignee_hint)
        if reply_assignee_hint and assignee_usernames == [reply_assignee_hint["token"]]:
            logger.info("Auto-assigned task from reply target: %s", reply_assignee_hint["token"])

        pending_task = PendingTask(
            message_id=message_obj.id,
            chat_id=message.chat.id,
            created_by_id=user.id,
            title=task_data.get("title", "Новая задача"),
            description=task_data.get("description"),
            assignee_usernames=assignee_usernames if assignee_usernames else None,
            assignee_username=assignee_usernames[0] if assignee_usernames else None,
            due_date=task_data.get("due_date_parsed"),
            priority=task_data.get("priority", "normal"),
            status="pending",
        )
        db.add(pending_task)
        db.commit()
        db.refresh(pending_task)

        if not assignee_usernames:
            logger.info("No assignee found, requesting assignee in private chat")
            chat_members = []
            try:
                chat_admins = await message.bot.get_chat_administrators(message.chat.id)
                for admin in chat_admins:
                    user_obj = admin.user
                    if not user_obj.is_bot:
                        chat_members.append({"id": user_obj.id, "username": user_obj.username, "first_name": user_obj.first_name})
            except Exception as e:
                logger.warning("Could not fetch chat administrators for assignee selection: %s", e)

            if not any(member["id"] == message.from_user.id for member in chat_members):
                chat_members.append({"id": message.from_user.id, "username": message.from_user.username, "first_name": message.from_user.first_name})

            try:
                if await send_private_assignee_selection(message.bot, user, pending_task, chat_members):
                    db.commit()
                    return
            except TelegramForbiddenError:
                logger.warning("Creator has not started the bot; cannot send assignee selection in private")
            except Exception as e:
                logger.error("Error sending private assignee selection: %s", e, exc_info=True)

            await send_creator_start_prompt(message.bot, message)
            return

        confirmation_text = (
            f"📋 <b>Подтвердите задачу</b>\n\n"
            f"<b>Задача:</b> {pending_task.title}\n"
        )
        if pending_task.description and pending_task.description != pending_task.title:
            confirmation_text += f"<b>Описание:</b> {pending_task.description}\n"
        if pending_task.assignee_usernames:
            if len(pending_task.assignee_usernames) == 1:
                confirmation_text += f"<b>Исполнитель:</b> @{pending_task.assignee_usernames[0]}\n"
            else:
                confirmation_text += f"<b>Исполнители:</b> {', '.join(f'@{u}' for u in pending_task.assignee_usernames)}\n"
        if pending_task.due_date:
            confirmation_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
        confirmation_text += f"<b>Приоритет:</b> {pending_task.priority}\n\nПодтвердить создание задачи?"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_task:{pending_task.id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_task:{pending_task.id}")]])
        confirmation_text = _build_pending_task_confirmation_text(db, pending_task)
        try:
            sent_message = await message.bot.send_message(
                chat_id=message.from_user.id,
                text=confirmation_text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            pending_task.telegram_message_id = sent_message.message_id
            db.commit()
            logger.info("Task confirmation sent to user %s", user.telegram_id)
        except TelegramForbiddenError:
            logger.warning("User has not started the bot; cannot send private confirmation")
            await send_creator_start_prompt(message.bot, message)
    except Exception as e:
        logger.error(f"Error handling group message: {e}", exc_info=True)
    finally:
        db.close()


@router.message(F.photo | F.document)
async def handle_file_upload(message: Message):
    """Обработчик загрузки файлов как отчёта по задаче."""
    db = get_db_session()

    try:
        
        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db
        )

        file_type = None
        file_id = None
        file_name = None
        file_size = None
        mime_type = None
        caption = message.caption
        referenced_task_id = extract_task_reference(caption)
        task, task_resolution_error = resolve_task_for_file_upload(db, user.id, caption)
        if task_resolution_error:
            await message.answer(task_resolution_error)
            return

        if message.photo:
            
            photo = message.photo[-1]
            file_type = "photo"
            file_id = photo.file_id
            file_size = photo.file_size
            file_name = f"photo_{photo.file_id[:10]}.jpg"
            mime_type = "image/jpeg"

        elif message.document:
            doc = message.document
            file_type = "document"
            file_id = doc.file_id
            file_name = doc.file_name
            file_size = doc.file_size
            mime_type = doc.mime_type

        
        task_file = TaskFile(
            task_id=task.id,
            uploaded_by_id=user.id,
            file_type=file_type,
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            caption=caption
        )

        db.add(task_file)
        db.commit()
        db.refresh(task_file)

        
        confirmation = (
            f"✅ <b>Файл прикреплён к задаче!</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Файл:</b> {file_name}\n"
        )

        if file_size:
            size_mb = file_size / 1024 / 1024
            confirmation += f"<b>Размер:</b> {size_mb:.2f} МБ\n"

        if caption:
            confirmation += f"<b>Описание:</b> {caption}\n"

        confirmation += f"\n📋 Руководитель сможет просмотреть отчёт в веб-панели"

        await message.answer(confirmation, parse_mode="HTML")

        logger.info(
            "File saved: task_id=%s, file_type=%s, file_id=%s, referenced_via_caption=%s",
            task.id,
            file_type,
            file_id,
            bool(referenced_task_id),
        )

    except Exception as e:
        logger.error(f"Error handling file upload: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при загрузке файла. Попробуйте позже.")
    finally:
        db.close()


@router.message()
async def handle_other_message(message: Message):
    """Обработчик остальных сообщений."""
    if message.chat.type == "private":
        await message.answer(
            "Привет! 👋\n\n"
            "Я работаю в групповых чатах. Добавьте меня в группу, чтобы я начал анализировать задачи.\n\n"
            "Используйте /help для получения справки."
        )
