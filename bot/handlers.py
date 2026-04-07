import logging
import re
from typing import List, Optional
from datetime import datetime, timedelta
from aiogram import Bot, Router, F
from aiogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup,
    CallbackQuery, PhotoSize, Document, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.orm import Session

from config import TASK_KEYWORDS, MINI_APP_URL, HOST, PORT, WEB_APP_DOMAIN
from db.models import User, Message as MessageModel, Task, Category, PendingTask, TaskFile, Chat
from db.database import get_db_session
from bot.ai_extractor import analyze_message, telegram_message_requires_context

logger = logging.getLogger(__name__)

router = Router()
TASK_REFERENCE_PATTERNS = [
    re.compile(r"#task\s*(\d+)", flags=re.IGNORECASE),
    re.compile(r"\btask\s*[:#]?\s*(\d+)\b", flags=re.IGNORECASE),
    re.compile(r"\bзадач[аеиу]?\s*#?\s*(\d+)\b", flags=re.IGNORECASE),
]


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
        query
        .order_by(MessageModel.date.desc(), MessageModel.id.desc())
        .limit(limit)
        .all()
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

        context_messages.append({
            "sender": sender_name,
            "date": item.date.strftime("%Y-%m-%d %H:%M:%S") if item.date else "",
            "text": item.text or "",
        })

    return context_messages


def _extract_task_reference(text: Optional[str]) -> Optional[int]:
    if not text:
        return None

    for pattern in TASK_REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))

    return None


def _get_user_in_progress_tasks(db: Session, user_id: int) -> List[Task]:
    return (
        db.query(Task)
        .join(Task.assignees)
        .filter(
            User.id == user_id,
            Task.status == "in_progress",
        )
        .all()
    )


def _build_file_upload_task_hint(tasks: List[Task]) -> str:
    visible_tasks = sorted(
        tasks,
        key=lambda item: item.updated_at or item.created_at or datetime.min,
        reverse=True,
    )[:5]
    task_lines = "\n".join(f"• #{task.id} {task.title}" for task in visible_tasks)

    return (
        "⚠️ У вас несколько задач в работе, поэтому я не буду гадать, к какой прикрепить файл.\n\n"
        "Добавьте в подпись к файлу ссылку на задачу, например: #task123\n\n"
        f"Сейчас у вас активны:\n{task_lines}"
    )


def _resolve_task_for_file_upload(db: Session, user_id: int, caption: Optional[str]) -> tuple[Optional[Task], Optional[str]]:
    active_tasks = _get_user_in_progress_tasks(db, user_id)

    if not active_tasks:
        return None, (
            "❌ У вас нет задач в процессе выполнения.\n\n"
            "Сначала начните выполнение задачи, нажав кнопку '▶️ Начать выполнение'."
        )

    referenced_task_id = _extract_task_reference(caption)
    if referenced_task_id is not None:
        matched_task = next((task for task in active_tasks if task.id == referenced_task_id), None)
        if matched_task is not None:
            return matched_task, None

        return None, (
            f"❌ Задача #{referenced_task_id} не найдена среди ваших задач в работе.\n\n"
            f"{_build_file_upload_task_hint(active_tasks)}"
        )

    if len(active_tasks) == 1:
        return active_tasks[0], None

    return None, _build_file_upload_task_hint(active_tasks)


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
        db.commit()
        db.refresh(user)
        logger.info(f"Created user placeholder by telegram id {telegram_id} (ID: {user.id})")
        return user

    user = db.query(User).filter(User.username == username).first()

    if not user:
        user = User(
            telegram_id=-1,
            username=username,
            first_name=f"@{username}",
            is_bot=False
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Created temporary user @{username} (ID: {user.id})")

    return user


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


async def notify_comment_added(bot: Bot, task_id: int, comment_author_id: int, comment_text: str, db: Session) -> None:
    """
    Отправляет уведомления о новом комментарии всем участникам задачи,
    кроме автора комментария.
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        comment_author = db.query(User).filter(User.id == comment_author_id).first()

        # Собираем всех участников задачи
        participants = set()

        # Добавляем создателя задачи
        if task.creator and task.creator.id != comment_author_id:
            participants.add(task.creator)

        # Добавляем всех исполнителей
        for assignee in task.assignees:
            if assignee.id != comment_author_id:
                participants.add(assignee)

        # Формируем уведомление
        notification = (
            f"💬 <b>Новый комментарий к задаче</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Автор:</b> {comment_author.first_name or comment_author.username}\n"
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
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    logger.info(f"Comment notification sent to user @{participant.username}")
                except TelegramForbiddenError:
                    logger.warning(f"User @{participant.username} blocked the bot")
                except Exception as e:
                    logger.error(f"Failed to send comment notification to @{participant.username}: {e}")
    except Exception as e:
        logger.error(f"Error in notify_comment_added: {e}", exc_info=True)


async def notify_assigned_user(bot: Bot, task_id: int, db: Session, assignee: User = None) -> bool:
    """Отправляет назначенному исполнителю уведомление о новой задаче."""
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
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
            assignees_str = ", ".join([f"@{a.username}" for a in task.assignees if a.username])
            if assignees_str:
                notification += f"<b>Исполнители:</b> {assignees_str}\n"
        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
        notification += f"<b>Приоритет:</b> {task.priority}\n"
        notification += f"<b>Статус:</b> {task.status}"

        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={assignee.id}&task_id={task.id}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))],
            [InlineKeyboardButton(text="▶️ Начать выполнение", callback_data=f"task_start:{task.id}")],
            [InlineKeyboardButton(text="✅ Завершить", callback_data=f"task_complete:{task.id}")],
        ])

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
    except Exception as e:
        logger.error(f"Failed to send notification: {e}", exc_info=True)
        return False

def _build_bot_start_url(bot_username: str, start_param: str = "taskbridge") -> str:
    return f"https://t.me/{bot_username}?start={start_param}"


def _format_user_mention(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return "Пользователь"


async def _send_assignee_start_prompt(bot: Bot, chat_id: int, assignee: User, task_title: str) -> None:
    bot_info = await bot.get_me()
    start_url = _build_bot_start_url(bot_info.username)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть чат с ботом", url=start_url)]])
    mention = _format_user_mention(assignee)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{mention}, вам назначили задачу <b>{task_title}</b>.\n\n"
            "Пожалуйста, перейдите в чат со мной и нажмите Start, чтобы получать задачи и работать с ними."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _send_creator_start_prompt(bot: Bot, source_message: Message) -> None:
    bot_info = await bot.get_me()
    start_url = _build_bot_start_url(bot_info.username)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть чат с ботом", url=start_url)]])
    mention = f"@{source_message.from_user.username}" if source_message.from_user.username else source_message.from_user.first_name
    await source_message.answer(
        f"{mention}, чтобы подтвердить задачу, перейдите в личный чат со мной и нажмите Start.",
        reply_markup=keyboard,
    )


async def _send_private_assignee_selection(bot: Bot, creator: User, pending_task: PendingTask, members: list[dict]) -> bool:
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
        row.append(InlineKeyboardButton(text=display_name[:24], callback_data=f"assign_user:{pending_task.id}:{member['id']}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_task:{pending_task.id}")])

    sent = await bot.send_message(
        chat_id=creator.telegram_id,
        text=ask_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    pending_task.telegram_message_id = sent.message_id
    return True


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start."""
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

        pending_tasks = db.query(Task).join(Task.assignees).filter(
            User.id == user.id,
            Task.status.in_(["pending", "in_progress"]),
        ).all()

        if pending_tasks:
            for task in pending_tasks:
                task_webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={user.id}&task_id={task.id}"
                task_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=task_webapp_url))]])
                notification = (
                    f"📌 <b>У вас есть активная задача</b>\n\n"
                    f"<b>{task.title}</b>\n"
                    f"Статус: {task.status}\n"
                    f"Приоритет: {task.priority}\n"
                )
                if task.due_date:
                    notification += f"Срок: {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
                await message.answer(notification, reply_markup=task_keyboard, parse_mode="HTML")

        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={user.id}"

        if is_first_auth and pending_tasks:
            welcome_message = (
                f"Добро пожаловать. У вас уже есть {len(pending_tasks)} активных задач.\n\n"
                "Откройте панель задач или переходите в карточки выше, чтобы продолжить работу."
            )
        elif pending_tasks:
            welcome_message = (
                f"С возвращением. У вас {len(pending_tasks)} активных задач.\n\n"
                "Откройте панель задач или используйте карточки выше, чтобы продолжить работу."
            )
        else:
            welcome_message = (
                "TaskBridge помогает фиксировать задачи из чатов и работать с ними в мини-приложении.\n\n"
                "Откройте панель задач, запустите агента или начните общение с поддержкой."
            )

        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть панель задач", web_app=WebAppInfo(url=webapp_url))],
            [InlineKeyboardButton(text="🤖 Агент", callback_data="agent_open")],
            [InlineKeyboardButton(text="💬 Поддержка", callback_data="support_start")],
        ])

        reply_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Панель задач", web_app=WebAppInfo(url=webapp_url))],
                [KeyboardButton(text="🤖 Агент")],
            ],
            resize_keyboard=True,
            persistent=True,
        )

        await message.answer(welcome_message, reply_markup=inline_keyboard, parse_mode="HTML")
        await message.answer("Ниже добавил постоянную клавиатуру для быстрого доступа.", reply_markup=reply_keyboard)
    except Exception as e:
        logger.error(f"Error in /start command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    """Обработчик команды /panel."""
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

        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={user.id}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть панель задач",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ])

        await message.answer("Нажмите кнопку ниже для доступа к панели задач:", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in /panel command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Показывает краткую справку по боту."""
    help_text = (
        "📘 <b>TaskBridge</b>\n\n"
        "<b>Команды:</b>\n"
        "/start — открыть стартовое меню и клавиатуру\n"
        "/panel — открыть панель задач\n"
        "/support — открыть чат поддержки\n"
        "/help — показать эту справку\n\n"
        "<b>Как это работает:</b>\n"
        "1. Напишите задачу в групповом чате.\n"
        "2. Бот распознает задачу и отправит подтверждение постановщику в личку.\n"
        "3. После подтверждения задача появится у исполнителя и в мини-приложении.\n\n"
        "Агент запускается кнопкой <b>🤖 Агент</b> в личном чате с ботом."
    )
    await message.answer(help_text, parse_mode="HTML")


@router.callback_query(F.data.startswith("task_start:"))
async def handle_task_start(callback: CallbackQuery):
    """Обработчик начала выполнения задачи."""
    db = get_db_session()

    try:
        task_id = int(callback.data.split(":")[1])
        task = db.query(Task).filter(Task.id == task_id).first()

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

        assignee_name = _format_user_mention(assignee)
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
                        await _send_assignee_start_prompt(callback.bot, pending_task.chat_id, assignee, task.title)
                    except Exception as e:
                        logger.error(f"Failed to send start prompt for assignee: {e}", exc_info=True)

        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?task_id={task.id}"
        if creator:
            webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=manager&user_id={creator.id}&task_id={task.id}"
        manager_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))]])

        confirmation_msg = (
            f"✅ <b>Задача подтверждена и создана</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )
        if task.assignees:
            if len(task.assignees) == 1:
                confirmation_msg += f"<b>Исполнитель:</b> {_format_user_mention(task.assignees[0])}\n"
            else:
                confirmation_msg += f"<b>Исполнители:</b> {', '.join(_format_user_mention(a) for a in task.assignees)}\n"
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
        task = db.query(Task).filter(Task.id == task_id).first()

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

        assignee_usernames = task_data.get("assignee_usernames", []) or []
        if not assignee_usernames and task_data.get("assignee_username"):
            assignee_usernames = [task_data.get("assignee_username")]

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
                if await _send_private_assignee_selection(message.bot, user, pending_task, chat_members):
                    db.commit()
                    return
            except TelegramForbiddenError:
                logger.warning("Creator has not started the bot; cannot send assignee selection in private")
            except Exception as e:
                logger.error("Error sending private assignee selection: %s", e, exc_info=True)

            await _send_creator_start_prompt(message.bot, message)
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
            await _send_creator_start_prompt(message.bot, message)
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

        # Находим активные задачи пользователя через many-to-many связь
        active_tasks = db.query(Task).join(
            Task.assignees
        ).filter(
            User.id == user.id,
            Task.status == "in_progress"
        ).all()

        if not active_tasks:
            await message.answer(
                "❌ У вас нет задач в процессе выполнения.\n\n"
                "Сначала начните выполнение задачи, нажав кнопку '▶️ Начать выполнение'."
            )
            return

        
        task = active_tasks[0]
        if len(active_tasks) > 1:
            task = max(active_tasks, key=lambda t: t.updated_at or t.created_at)
            logger.info(f"User has {len(active_tasks)} active tasks, using most recent: {task.id}")

        
        file_type = None
        file_id = None
        file_name = None
        file_size = None
        mime_type = None
        caption = message.caption
        referenced_task_id = _extract_task_reference(caption)
        task, task_resolution_error = _resolve_task_for_file_upload(db, user.id, caption)
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
