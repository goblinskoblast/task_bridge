import logging
import re
from typing import List, Optional
from datetime import datetime
from aiogram import Bot, Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.orm import Session

from config import TASK_KEYWORDS, MINI_APP_URL
from db.models import User, Message as MessageModel, Task, Category, PendingTask
from db.database import get_db_session
from bot.ai_extractor import analyze_message

logger = logging.getLogger(__name__)

router = Router()


def init_default_categories(db: Session):
    
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
    """Классификация задачи по категориям на основе keywords из БД"""
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


async def notify_assigned_user(bot: Bot, task_id: int, db: Session):
    
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not task.assignee:
            return

        assignee = task.assignee

        
        if assignee.telegram_id == -1 or assignee.telegram_id is None:
            logger.warning(f"User @{assignee.username} hasn't started a chat with the bot")
            return

        
        notification = (
            f"🔔 <b>Вам назначена новая задача</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>Приоритет:</b> {task.priority}\n"

        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено",
                    callback_data=f"task_complete:{task.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Открыть панель",
                    web_app=WebAppInfo(url=MINI_APP_URL)
                )
            ]
        ])

        
        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=notification,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        logger.info(f"Notification sent to user @{assignee.username} (ID: {assignee.telegram_id})")

    except TelegramForbiddenError:
        logger.warning(f"User blocked the bot or hasn't started it")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


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

        
        if user.telegram_id == -1 or user.telegram_id != message.from_user.id:
            user.telegram_id = message.from_user.id
            db.commit()
            logger.info(f"Updated telegram_id for user @{user.username} (ID: {user.id})")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 Панель задач",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )]
        ])

        welcome_message = (
            "✅ Отлично! Теперь вы будете получать уведомления о задачах.\n\n"
            "🤖 TaskBridge использует AI для автоматического извлечения задач из чатов.\n\n"
            "Добавьте меня в групповой чат, чтобы я начал анализировать сообщения."
        )

        await message.answer(welcome_message, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in /start command: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        db.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "📋 <b>TaskBridge - AI-управление задачами</b>\n\n"
        "<b>Команды:</b>\n"
        "/start - Начать работу\n"
        "/help - Показать справку\n"
        "/panel - Открыть панель управления\n\n"
        "<b>Как использовать:</b>\n"
        "1. Добавьте бота в групповой чат\n"
        "2. Пишите сообщения с задачами, например:\n"
        "   • <i>@alex сделай отчет до завтра</i>\n"
        "   • <i>Саша, срочно исправь баг к вечеру</i>\n"
        "3. Бот автоматически извлечет задачу с помощью AI\n"
        "4. Подтвердите задачу или отредактируйте её\n"
        "5. Исполнитель получит уведомление\n\n"
        "🤖 <b>AI автоматически определяет:</b>\n"
        "• Описание задачи\n"
        "• Исполнителя (@username или имя)\n"
        "• Срок выполнения\n"
        "• Приоритет"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📋 Открыть панель управления",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])

    await message.answer(help_text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    """Обработчик команды /panel - открывает веб-приложение"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📋 Открыть панель управления",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])

    await message.answer(
        "Откройте панель управления для просмотра всех задач:",
        reply_markup=keyboard
    )


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

        
        assigned_user_id = None
        if pending_task.assignee_username:
            assignee = await get_or_create_user_by_username(db, pending_task.assignee_username)
            assigned_user_id = assignee.id

        
        category_id = classify_task(pending_task.description or pending_task.title, db)

        
        task = Task(
            message_id=pending_task.message_id,
            category_id=category_id,
            assigned_to=assigned_user_id,
            title=pending_task.title,
            description=pending_task.description,
            status="pending",
            priority=pending_task.priority,
            due_date=pending_task.due_date
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        
        pending_task.status = "confirmed"
        db.commit()

       
        if assigned_user_id:
            await notify_assigned_user(callback.bot, task.id, db)

        
        await callback.message.edit_text(
            f"✅ <b>Задача подтверждена и отправлена!</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Исполнитель:</b> @{pending_task.assignee_username if pending_task.assignee_username else 'не указан'}\n"
            f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'не указан'}\n"
            f"<b>Приоритет:</b> {task.priority}",
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

       
        user = await get_or_create_user(
            bot=message.bot,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
            db=db
        )

        
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

        
        logger.info(f"Analyzing message: {message.text[:50]}...")
        ai_result = await analyze_message(message.text or "", use_ai=True)

        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in message")
            return

        
        message_obj.has_task = True
        db.commit()

        task_data = ai_result.get("task", {})

        
        pending_task = PendingTask(
            message_id=message_obj.id,
            chat_id=message.chat.id,
            created_by_id=user.id,
            title=task_data.get("title", "Без названия"),
            description=task_data.get("description"),
            assignee_username=task_data.get("assignee_username"),
            due_date=task_data.get("due_date_parsed"),
            priority=task_data.get("priority", "normal"),
            status="pending"
        )

        db.add(pending_task)
        db.commit()
        db.refresh(pending_task)

        
        confirmation_text = (
            f"🤖 <b>AI обнаружил задачу!</b>\n\n"
            f"<b>Задача:</b> {pending_task.title}\n"
        )

        if pending_task.description and pending_task.description != pending_task.title:
            confirmation_text += f"<b>Описание:</b> {pending_task.description}\n"

        if pending_task.assignee_username:
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


@router.message()
async def handle_other_message(message: Message):
    """Обработчик остальных сообщений"""
    if message.chat.type == "private":
        await message.answer(
            "Привет! 👋\n\n"
            "Я работаю в групповых чатах. Добавьте меня в группу, чтобы я начал анализировать задачи.\n\n"
            "Используйте /help для получения справки."
        )
