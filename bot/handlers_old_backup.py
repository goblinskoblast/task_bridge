import logging
import re
from typing import List, Optional
from aiogram import Bot, Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.orm import Session

from config import TASK_KEYWORDS, MINI_APP_URL
from db.models import User, Message as MessageModel, Task, Category
from db.database import get_db_session

logger = logging.getLogger(__name__)


router = Router()


def extract_tasks(text: str) -> bool:
    
    if not text:
        return False
    
    text_lower = text.lower()
    
  
    for keyword in TASK_KEYWORDS:
        if keyword in text_lower:
            return True
    
   
    if '@' in text:
        return True
    
    return False


def extract_mentions(text: str) -> List[str]:
    
    if not text:
        return []
    
 
    mentions = re.findall(r'@(\w+)', text)
    return mentions


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


async def notify_assigned_user(bot: Bot, db: Session, username: str, task_text: str, group_chat_id: int = None):
    
    try:
      
        user = await get_or_create_user_by_username(db, username)
        
        if not user:
            logger.warning(f"Failed to get or create user @{username}")
            
            if group_chat_id:
                try:
                    await bot.send_message(
                        chat_id=group_chat_id,
                        text=f"❌ Пользователь @{username} не найден в системе."
                    )
                except:
                    pass
            return
        
       
        if user.telegram_id == -1 or user.telegram_id is None:
            logger.warning(f"User @{username} hasn't started a chat with the bot")
           
            if group_chat_id:
                try:
                    await bot.send_message(
                        chat_id=group_chat_id,
                        text=(
                            f"👋 @{username}, пожалуйста, начни чат со мной (/start), "
                            f"чтобы получать уведомления о задачах."
                        )
                    )
                except Exception as group_error:
                    logger.error(f"Failed to send group notification: {group_error}")
            return
        
        
        notification = (
            f"🔔 Вам назначена новая задача:\n\n"
            f"{task_text}\n\n"
            f"Откройте панель управления для просмотра всех задач."
        )
        
        
        await bot.send_message(
            chat_id=user.telegram_id,
            text=notification
        )
        
        logger.info(f"Notification sent to user @{username} (ID: {user.telegram_id})")
        
    except TelegramForbiddenError:
        logger.warning(f"User @{username} blocked the bot or hasn't started it")
        
       
        if group_chat_id:
            try:
                await bot.send_message(
                    chat_id=group_chat_id,
                    text=(
                        f"👋 @{username}, пожалуйста, начни чат со мной (/start), "
                        f"чтобы получать уведомления о задачах."
                    )
                )
            except Exception as group_error:
                logger.error(f"Failed to send group notification: {group_error}")
    
    except Exception as e:
        logger.error(f"Failed to send notification to @{username}: {e}")
        
        
        if group_chat_id:
            try:
                await bot.send_message(
                    chat_id=group_chat_id,
                    text=f"⚠️ Не удалось отправить уведомление @{username}"
                )
            except:
                pass


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
            "📋 TaskBridge поможет вам отслеживать задачи из групповых чатов.\n\n"
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
        "📋 TaskBridge - Управление задачами\n\n"
        "Команды:\n"
        "/start - Начать работу\n"
        "/help - Показать справку\n"
        "/panel - Открыть панель управления\n\n"
        "Как использовать:\n"
        "1. Добавьте бота в групповой чат\n"
        "2. Напишите сообщение с задачей (например: @username нужно сделать...)\n"
        "3. Бот автоматически извлечет задачу и уведомит сотрудника\n"
        "4. Откройте панель управления для просмотра всех задач"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📋 Открыть панель управления",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])
    
    await message.answer(help_text, reply_markup=keyboard)


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


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message(message: Message):
    """Обработчик сообщений из групповых чатов"""
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
        
        
        has_task = extract_tasks(message.text or "")
        
        if has_task:
            message_obj.has_task = True
            db.commit()
            
            
            mentions = extract_mentions(message.text or "")
            
            
            category_id = classify_task(message.text or "", db)
            
            
            assigned_user_id = None
            if mentions:
                
                assigned_user = db.query(User).filter(User.username == mentions[0]).first()
                if assigned_user:
                    assigned_user_id = assigned_user.id
                    
                    db.refresh(message_obj)
            
            
            task = Task(
                message_id=message_obj.id,
                category_id=category_id,
                assigned_to=assigned_user_id,
                title=message.text[:500] if message.text else "Задача без описания",
                description=message.text,
                status="pending"
            )
            
            db.add(task)
            db.commit()
            
            logger.info(f"Task created from message {message.message_id} in chat {message.chat.id}")
            
            
            if mentions:
                for mention in mentions:
                    await notify_assigned_user(
                        message.bot, 
                        db, 
                        mention, 
                        message.text or "",
                        group_chat_id=message.chat.id
                    )
        
        db.commit()
        
    except Exception as e:
        logger.error(f"Error handling group message: {e}")
    finally:
        db.close()


@router.message()
async def handle_other_message(message: Message):
    
    if message.chat.type == "private":
        await message.answer(
            "Привет! 👋\n\n"
            "Я работаю в групповых чатах. Добавьте меня в группу, чтобы я начал анализировать задачи.\n\n"
            "Используйте /help для получения справки."
        )
