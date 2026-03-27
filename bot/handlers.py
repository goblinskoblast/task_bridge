import logging
import re
from typing import List, Optional
from datetime import datetime
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
from bot.ai_extractor import analyze_message

logger = logging.getLogger(__name__)

router = Router()


def get_recent_chat_context(
    db: Session,
    chat_id: int,
    current_message_db_id: int,
    limit: int = 8
) -> List[dict]:
    """Return recent chat messages for context-aware task extraction."""
    recent_messages = (
        db.query(MessageModel)
        .filter(
            MessageModel.chat_id == chat_id,
            MessageModel.id != current_message_db_id,
            MessageModel.text.isnot(None)
        )
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


def init_default_categories(db: Session):
    """Инициализация стандартных категорий задач"""
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
            "description": "Аналитические и отчетные задачи",
            "keywords": ["аналитик", "отчет", "статистик", "metric", "dashboard", "kpi", "analytics", "data", "metric", "report", "analysis"]
        },
        {
            "name": "Встречи",
            "description": "Встречи и переговоры",
            "keywords": ["встреч", "собрание", "звонок", "онлайн", "meeting", "call", "conference", "presentation"]
        },
        {
            "name": "uncategorized",
            "description": "Задачи без определенной категории",
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
    """Получает пользователя из БД или создает нового"""
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
    """Получает чат из БД или создает новый"""
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
        # Обновляем информацию о чате, если изменилась
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
    Отправляет уведомления о новом комментарии всем участникам задачи
    (создателю и исполнителям), кроме автора комментария.
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        comment_author = db.query(User).filter(User.id == comment_author_id).first()

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
    """
    Отправляет уведомление исполнителю о назначении задачи.
    Если assignee не указан, берет первого исполнителя из task.assignees (для обратной совместимости).
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        # Если исполнитель не передан, берем из связей задачи
        if not assignee:
            if task.assignees:
                assignee = task.assignees[0]
            else:
                logger.warning(f"Task {task_id} has no assignees")
                return False

        # Проверяем, что у пользователя есть telegram_id
        if assignee.telegram_id == -1 or assignee.telegram_id is None:
            logger.warning(f"User @{assignee.username} hasn't started a chat with the bot")
            return False

        # Формируем уведомление
        notification = (
            f"🔔 <b>Вам назначена новая задача</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"

        # Показываем всех исполнителей, если их несколько
        if len(task.assignees) > 1:
            assignees_str = ", ".join([f"@{a.username}" for a in task.assignees if a.username])
            notification += f"<b>Исполнители:</b> {assignees_str}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>Приоритет:</b> {task.priority}\n"
        notification += f"<b>Статус:</b> {task.status}\n"

        # Кнопки
        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={assignee.id}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть панель",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Начать выполнение",
                    callback_data=f"task_start:{task.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Выполнено",
                    callback_data=f"task_complete:{task.id}"
                )
            ]
        ])

        # Отправляем сообщение
        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=notification,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        logger.info(f"Notification sent to user @{assignee.username} (ID: {assignee.telegram_id})")
        return True

    except TelegramForbiddenError:
        logger.warning(f"User blocked the bot or hasn't started it")
        return False
    except Exception as e:
        logger.error(f"Failed to send notification: {e}", exc_info=True)
        return False


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
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

        # Флаг первой авторизации - если пользователь был создан по username без telegram_id
        is_first_auth = (user.telegram_id == -1 or user.telegram_id != message.from_user.id)

        # Обновляем telegram_id если пользователь ранее был создан по username
        if is_first_auth:
            user.telegram_id = message.from_user.id
            db.commit()
            logger.info(f"Updated telegram_id for user @{user.username} (ID: {user.id})")

        # Проверяем незавершенные задачи пользователя
        pending_tasks = db.query(Task).join(Task.assignees).filter(
            User.id == user.id,
            Task.status.in_(["pending", "in_progress"])
        ).all()

        # Отправляем уведомления о незавершенных задачах
        if pending_tasks:
            for task in pending_tasks:
                task_webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={user.id}&task_id={task.id}"
                task_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📱 Открыть задачу",
                            web_app=WebAppInfo(url=task_webapp_url)
                        )
                    ]
                ])

                notification = (
                    f"📋 <b>У вас есть незавершенная задача</b>\n\n"
                    f"<b>{task.title}</b>\n"
                    f"Статус: {task.status}\n"
                    f"Приоритет: {task.priority}\n"
                )

                if task.due_date:
                    notification += f"Срок: {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

                await message.answer(notification, reply_markup=task_keyboard, parse_mode="HTML")

        webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=executor&user_id={user.id}"

        # Формируем приветственное сообщение
        if is_first_auth and pending_tasks:
            welcome_message = (
                f"✅ Добро пожаловать! Вам было назначено {len(pending_tasks)} задач.\n\n"
                "Вы можете открыть панель задач через кнопку ниже или использовать постоянную кнопку над клавиатурой."
            )
        elif pending_tasks:
            welcome_message = (
                f"✅ С возвращением! У вас {len(pending_tasks)} незавершенных задач.\n\n"
                "Используйте кнопку ниже или постоянную кнопку для доступа к панели задач."
            )
        else:
            welcome_message = (
                "✅ Отлично! Теперь вы будете получать уведомления о задачах.\n\n"
                "🤖 TaskBridge использует AI для автоматического извлечения задач из чатов.\n\n"
                "Добавьте меня в групповой чат, чтобы я начал анализировать сообщения.\n\n"
                "Используйте кнопку \"📱 Панель задач\" для быстрого доступа к вашим задачам."
            )

        # Inline кнопка для одноразового использования
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть мою панель задач",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ],
            [InlineKeyboardButton(
                    text="💬 Чат поддержки",
                    callback_data="support_start"
                )
            ]
        ])

        # Постоянная клавиатура с кнопкой быстрого доступа
        reply_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="📱 Панель задач",
                        web_app=WebAppInfo(url=webapp_url)
                    )
                ]
            ],
            resize_keyboard=True,
            persistent=True
        )

        await message.answer(
            welcome_message,
            reply_markup=inline_keyboard,
            parse_mode="HTML"
        )

        # Отправляем отдельное сообщение с постоянной клавиатурой
        await message.answer(
            "Используйте кнопку ниже для быстрого доступа:",
            reply_markup=reply_keyboard
        )

    except Exception as e:
        logger.error(f"Error in /start command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    """Обработчик команды /panel - открыть панель задач"""
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
    """Справка по боту без чат-сценария регистрации email."""
    help_text = (
        "📋 <b>TaskBridge</b>\n\n"
        "<b>Команды:</b>\n"
        "/start - запуск и быстрый доступ к панели\n"
        "/panel - открыть панель задач\n"
        "/dataagent - диалог с DataAgent\n"
        "/connect - подключить внешнюю систему для DataAgent\n"
        "/systems - список систем DataAgent\n"
        "/support - чат поддержки\n"
        "/help - справка\n\n"
        "<b>Как работать:</b>\n"
        "1. Добавьте бота в рабочий чат\n"
        "2. Пишите задачи в сообщениях (с @username или именем исполнителя)\n"
        "3. Подтверждайте найденные задачи и контролируйте статус в панели\n\n"
        "📧 <b>Email интеграция:</b> подключается только через веб-панель в разделе Email.\n"
        "🤖 <b>DataAgent:</b> отдельный контур для аналитических запросов, внешних систем, почты и календаря."
    )

    await message.answer(help_text, parse_mode="HTML")




@router.callback_query(F.data.startswith("task_start:"))
async def handle_task_start(callback: CallbackQuery):
    """Обработчик начала выполнения задачи"""
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
        notification += f"\n📎 Можете отправить фото/файлы как отчёт"

        
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
    """Обработчик выбора исполнителя из группового чата"""
    db = get_db_session()

    try:
        # Парсим callback data: assign_user:{pending_task_id}:{telegram_user_id}
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка: неверный формат данных", show_alert=True)
            return

        pending_task_id = int(parts[1])
        selected_telegram_id = int(parts[2])

        # Проверяем что callback вызван создателем задачи
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()
        if not pending_task:
            await callback.answer("Задача не найдена", show_alert=True)
            return

        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        if not creator or creator.telegram_id != callback.from_user.id:
            await callback.answer("Только создатель задачи может выбрать исполнителя", show_alert=True)
            return

        # Находим или создаем пользователя-исполнителя
        assignee = db.query(User).filter(User.telegram_id == selected_telegram_id).first()
        if not assignee:
            # Создаем временного пользователя (будет обновлен когда он запустит бота)
            assignee = User(
                telegram_id=selected_telegram_id,
                username=callback.message.reply_markup.inline_keyboard[0][0].text,  # Берем имя из кнопки
                is_bot=False
            )
            db.add(assignee)
            db.commit()
            db.refresh(assignee)

        # Обновляем pending_task с выбранным исполнителем
        pending_task.assignee_usernames = [assignee.username] if assignee.username else []
        pending_task.assignee_username = assignee.username
        db.commit()

        # Удаляем сообщение с кнопками из группы
        try:
            await callback.message.delete()
        except:
            pass

        # Отправляем подтверждение В ЛИЧНЫЕ СООБЩЕНИЯ создателю
        assignee_name = assignee.first_name or assignee.username or f"User {assignee.telegram_id}"

        confirmation_text = (
            f"✅ <b>Исполнитель выбран!</b>\n\n"
            f"<b>Задача:</b> {pending_task.title}\n"
            f"<b>Исполнитель:</b> {assignee_name}\n"
        )

        if pending_task.description:
            confirmation_text += f"<b>Описание:</b> {pending_task.description}\n"

        if pending_task.due_date:
            confirmation_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        confirmation_text += f"<b>Приоритет:</b> {pending_task.priority}\n\n"
        confirmation_text += "Подтвердите создание задачи:"

        # Кнопки подтверждения
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_task:{pending_task.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_task:{pending_task.id}"
                )
            ]
        ])

        # Отправляем в личные сообщения
        await callback.bot.send_message(
            chat_id=creator.telegram_id,
            text=confirmation_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer(f"Исполнитель назначен: {assignee_name}")
        logger.info(f"User {assignee.telegram_id} assigned to pending_task {pending_task.id}")

    except TelegramForbiddenError:
        await callback.answer(
            "Не могу отправить подтверждение в личные сообщения. Начните чат с ботом командой /start",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Error in assign_user callback: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("confirm_task:"))
async def handle_confirm_task(callback: CallbackQuery):
    """Обработчик подтверждения задачи"""
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

        # Определяем исполнителей (поддержка нового и старого формата)
        assignee_usernames = pending_task.assignee_usernames or []
        if not assignee_usernames and pending_task.assignee_username:
            assignee_usernames = [pending_task.assignee_username]

        # Классифицируем задачу
        category_id = classify_task(pending_task.description or pending_task.title, db)

        # Если дедлайн не указан, ставим +24 часа от текущего времени
        due_date = pending_task.due_date
        if not due_date:
            from datetime import datetime, timedelta
            due_date = datetime.now() + timedelta(hours=24)

        # Создаем задачу
        task = Task(
            message_id=pending_task.message_id,
            category_id=category_id,
            created_by=pending_task.created_by_id,  # Сохраняем создателя
            title=pending_task.title,
            description=pending_task.description,
            status="pending",
            priority=pending_task.priority,
            due_date=due_date
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        # Назначаем исполнителей (many-to-many)
        if assignee_usernames:
            for username in assignee_usernames:
                assignee = await get_or_create_user_by_username(db, username)
                task.assignees.append(assignee)
            db.commit()

        from bot.calendar_sync import sync_task_to_connected_calendars
        sync_task_to_connected_calendars(task, db)

        # Отмечаем pending task как подтвержденный
        pending_task.status = "confirmed"
        db.commit()

        # Уведомляем всех исполнителей
        if task.assignees:
            for assignee in task.assignees:
                # Отправляем личное уведомление конкретному исполнителю
                notification_sent = await notify_assigned_user(callback.bot, task.id, db, assignee=assignee)

                # Если уведомление не отправлено (пользователь не начал чат с ботом)
                if not notification_sent and assignee.username:
                    try:
                        await callback.bot.send_message(
                            chat_id=pending_task.chat_id,
                            text=f"@{assignee.username}, вам назначена задача: <b>{task.title}</b>\n\n",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send group notification: {e}")

        
        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        webapp_url = (
            f"{WEB_APP_DOMAIN}/webapp/index.html?mode=manager&user_id={creator.id}&task_id={task.id}"
            if creator else
            f"{WEB_APP_DOMAIN}/webapp/index.html?task_id={task.id}"
        )

        
        manager_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть панель управления",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ])

        # Формируем текст с исполнителями
        confirmation_msg = (
            f"✅ <b>Задача подтверждена и отправлена!</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )

        if task.assignees:
            if len(task.assignees) == 1:
                confirmation_msg += f"<b>Исполнитель:</b> @{task.assignees[0].username}\n"
            else:
                assignees_str = ", ".join([f"@{a.username}" for a in task.assignees if a.username])
                confirmation_msg += f"<b>Исполнители:</b> {assignees_str}\n"
        else:
            confirmation_msg += f"<b>Исполнитель:</b> не указан\n"

        confirmation_msg += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'не указан'}\n"
        confirmation_msg += f"<b>Приоритет:</b> {task.priority}"

        await callback.message.edit_text(
            confirmation_msg,
            reply_markup=manager_keyboard,
            parse_mode="HTML"
        )

        await callback.answer("Задача создана! ✅")

    except Exception as e:
        logger.error(f"Error confirming task: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("reject_task:"))
async def handle_reject_task(callback: CallbackQuery):
    """Обработчик отклонения задачи"""
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
    """Обработчик отметки задачи как выполненной"""
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
    """Обработчик сообщений из групповых чатов с AI-извлечением задач"""
    db = get_db_session()

    try:

        if message.from_user.is_bot:
            return

        # Регистрируем/обновляем чат в базе данных
        chat = await get_or_create_chat(
            chat_id=message.chat.id,
            chat_type=message.chat.type,
            title=message.chat.title,
            username=message.chat.username,
            db=db
        )


        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db
        )


        if not message.text:
            logger.info("Message without text, skipping")
            return

        
        message_obj = MessageModel(
            message_id=message.message_id,
            chat_id=message.chat.id,
            user_id=user.id,
            text=message.text,
            date=message.date,
            has_task=False
        )

        db.add(message_obj)
        db.commit()
        db.refresh(message_obj)

        context_messages = get_recent_chat_context(
            db=db,
            chat_id=message.chat.id,
            current_message_db_id=message_obj.id,
        )

        logger.info(
            f"Analyzing message with {len(context_messages)} context items: "
            f"{message.text[:50]}..."
        )
        ai_result = await analyze_message(
            message.text,
            use_ai=True,
            context_messages=context_messages
        )

        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in message")
            return

        
        message_obj.has_task = True
        db.commit()

        task_data = ai_result.get("task", {})

        # Логируем данные от AI
        logger.info(f"Task data from AI: {task_data}")

        # Извлекаем список исполнителей (новый формат) или fallback на старый
        assignee_usernames = task_data.get("assignee_usernames", [])
        if not assignee_usernames:
            # Fallback на старое поле для обратной совместимости
            old_assignee = task_data.get("assignee_username")
            if old_assignee:
                assignee_usernames = [old_assignee]

        logger.info(f"Assignee usernames from AI: {assignee_usernames}")

        # НОВАЯ ЛОГИКА: Если нет исполнителя - спрашиваем в ГРУППОВОМ чате
        if not assignee_usernames:
            logger.info("No assignee found - asking in group chat")

            try:
                # Получаем участников чата
                chat_admins = await message.bot.get_chat_administrators(message.chat.id)
                chat_members = []

                for admin in chat_admins:
                    user_obj = admin.user
                    if not user_obj.is_bot:
                        chat_members.append({
                            'id': user_obj.id,
                            'username': user_obj.username,
                            'first_name': user_obj.first_name
                        })

                # Добавляем автора сообщения если его нет в списке
                author_in_list = any(m['id'] == message.from_user.id for m in chat_members)
                if not author_in_list and not message.from_user.is_bot:
                    chat_members.append({
                        'id': message.from_user.id,
                        'username': message.from_user.username,
                        'first_name': message.from_user.first_name
                    })

                if not chat_members:
                    logger.warning("No chat members found, cannot ask for assignee")
                    # Пропускаем создание задачи если нет участников
                    return

                # Создаем временный pending task БЕЗ исполнителя
                # но сохраняем его для последующего выбора
                pending_task = PendingTask(
                    message_id=message_obj.id,
                    chat_id=message.chat.id,
                    created_by_id=user.id,
                    title=task_data.get("title", "Без названия"),
                    description=task_data.get("description"),
                    assignee_usernames=None,  # Будет назначен после выбора
                    due_date=task_data.get("due_date_parsed"),
                    priority=task_data.get("priority", "normal"),
                    status="pending"
                )

                db.add(pending_task)
                db.commit()
                db.refresh(pending_task)

                # Формируем сообщение с кнопками выбора исполнителя В ГРУППЕ
                ask_text = (
                    f"🤖 <b>Обнаружена задача без исполнителя</b>\n\n"
                    f"<b>Задача:</b> {pending_task.title}\n"
                )

                if pending_task.description:
                    ask_text += f"<b>Описание:</b> {pending_task.description}\n"

                ask_text += f"\n{message.from_user.first_name}, кому назначить эту задачу?"

                # Создаем кнопки с участниками (максимум 2 в ряд)
                buttons = []
                row = []
                for member in chat_members:
                    display_name = member['first_name'] or member['username'] or f"User {member['id']}"
                    row.append(InlineKeyboardButton(
                        text=display_name[:20],  # Ограничиваем длину
                        callback_data=f"assign_user:{pending_task.id}:{member['id']}"
                    ))

                    if len(row) == 2:
                        buttons.append(row)
                        row = []

                # Добавляем остаток
                if row:
                    buttons.append(row)

                # Кнопка отмены
                buttons.append([
                    InlineKeyboardButton(
                        text="❌ Отменить задачу",
                        callback_data=f"reject_task:{pending_task.id}"
                    )
                ])

                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

                # Отправляем ПРЯМО В ГРУППУ
                await message.answer(
                    ask_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

                logger.info(f"Sent assignee selection to group chat {message.chat.id}")
                return  # Выходим, не создаем обычный pending task

            except Exception as e:
                logger.error(f"Error asking for assignee: {e}", exc_info=True)
                # Если не смогли спросить - создаем задачу без исполнителя
                assignee_usernames = []

        # Создаем pending task (только если исполнитель УЖЕ известен)
        pending_task = PendingTask(
            message_id=message_obj.id,
            chat_id=message.chat.id,
            created_by_id=user.id,
            title=task_data.get("title", "Без названия"),
            description=task_data.get("description"),
            assignee_usernames=assignee_usernames if assignee_usernames else None,
            assignee_username=assignee_usernames[0] if assignee_usernames else None,  # Для обратной совместимости
            due_date=task_data.get("due_date_parsed"),
            priority=task_data.get("priority", "normal"),
            status="pending"
        )

        logger.info(f"Created pending task with assignees: {pending_task.assignee_usernames}")

        db.add(pending_task)
        db.commit()
        db.refresh(pending_task)

        # Формируем текст подтверждения
        confirmation_text = (
            f"🤖 <b>AI обнаружил задачу!</b>\n\n"
            f"<b>Задача:</b> {pending_task.title}\n"
        )

        if pending_task.description and pending_task.description != pending_task.title:
            confirmation_text += f"<b>Описание:</b> {pending_task.description}\n"

        # Показываем всех исполнителей
        if pending_task.assignee_usernames:
            if len(pending_task.assignee_usernames) == 1:
                confirmation_text += f"<b>Исполнитель:</b> @{pending_task.assignee_usernames[0]}\n"
            else:
                assignees_str = ", ".join([f"@{u}" for u in pending_task.assignee_usernames])
                confirmation_text += f"<b>Исполнители:</b> {assignees_str}\n"
        elif pending_task.assignee_username:
            # Fallback на старое поле
            confirmation_text += f"<b>Исполнитель:</b> @{pending_task.assignee_username}\n"

        if pending_task.due_date:
            confirmation_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        confirmation_text += f"<b>Приоритет:</b> {pending_task.priority}\n\n"
        confirmation_text += "Подтвердите создание задачи:"

       
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_task:{pending_task.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_task:{pending_task.id}"
                )
            ]
        ])

        
        sent_message = await message.bot.send_message(
            chat_id=message.from_user.id,
            text=confirmation_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        
        pending_task.telegram_message_id = sent_message.message_id
        db.commit()

        logger.info(f"Task confirmation sent to user {user.telegram_id}")

    except TelegramForbiddenError:
        logger.warning(f"User hasn't started the bot, cannot send confirmation")
        try:
            await message.answer(
                f"👋 {message.from_user.first_name}, пожалуйста, начните чат со мной (/start), "
                f"чтобы подтверждать задачи!"
            )
        except:
            pass
    except Exception as e:
        logger.error(f"Error handling group message: {e}", exc_info=True)
    finally:
        db.close()


@router.message(F.photo | F.document)
async def handle_file_upload(message: Message):
    """Обработчик загрузки файлов (фото, документы) как отчёт по задаче"""
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

        # Находим активные задачи пользователя (через many-to-many связь)
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

        logger.info(f"File saved: task_id={task.id}, file_type={file_type}, file_id={file_id}")

    except Exception as e:
        logger.error(f"Error handling file upload: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при загрузке файла. Попробуйте позже.")
    finally:
        db.close()


@router.message()
async def handle_other_message(message: Message):
    """Обработчик остальных сообщений"""
    if message.chat.type == "private":
        await message.answer(
            "Привет! 👋\n\n"
            "Я работаю в групповых чатах. Добавьте меня в группу, чтобы я начал анализировать задачи.\n\n"
            "Используйте /help для получения справки."
        )


