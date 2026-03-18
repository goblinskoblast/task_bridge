import logging
import re
from urllib.parse import urlencode
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

from config import TASK_KEYWORDS, MINI_APP_URL, HOST, PORT, WEB_APP_DOMAIN, WEBAPP_BUILD_TAG
from db.models import User, Message as MessageModel, Task, Category, PendingTask, TaskFile, Chat
from db.database import get_db_session
from bot.ai_extractor import analyze_message

logger = logging.getLogger(__name__)

router = Router()

def build_webapp_url(mode: str = "executor", user_id: Optional[int] = None, task_id: Optional[int] = None) -> str:
    base = f"{WEB_APP_DOMAIN}/webapp/index.html"
    params = {"v": WEBAPP_BUILD_TAG}
    if mode:
        params["mode"] = mode
    if user_id is not None:
        params["user_id"] = str(user_id)
    if task_id is not None:
        params["task_id"] = str(task_id)
    return f"{base}?{urlencode(params)}"


def init_default_categories(db: Session):
    """РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ СЃС‚Р°РЅРґР°СЂС‚РЅС‹С… РєР°С‚РµРіРѕСЂРёР№ Р·Р°РґР°С‡"""
    default_categories = [
        {
            "name": "Р Р°Р·СЂР°Р±РѕС‚РєР°",
            "description": "Р—Р°РґР°С‡Рё РїРѕ СЂР°Р·СЂР°Р±РѕС‚РєРµ Рё РїСЂРѕРіСЂР°РјРјРёСЂРѕРІР°РЅРёСЋ",
            "keywords": ["РєРѕРґ", "РїСЂРѕРіСЂР°РјРј", "СЂР°Р·СЂР°Р±РѕС‚", "git", "commit", "repo", "repository", "bug", "issue", "pull request", "merge", "deploy", "dev", "development", "backend", "frontend", "api", "endpoint", "database", "sql", "query"]
        },
        {
            "name": "Р”РёР·Р°Р№РЅ",
            "description": "Р—Р°РґР°С‡Рё РїРѕ РґРёР·Р°Р№РЅСѓ Рё РІРёР·СѓР°Р»РёР·Р°С†РёРё",
            "keywords": ["РґРёР·Р°Р№РЅ", "РјР°РєРµС‚", "ui", "ux", "СЂРёСЃСѓРЅ", "СЌСЃРєРёР·", "mockup", "wireframe", "prototype", "figma", "sketch", "illustration", "graphics", "visual", "interface"]
        },
        {
            "name": "РњР°СЂРєРµС‚РёРЅРі",
            "description": "РњР°СЂРєРµС‚РёРЅРіРѕРІС‹Рµ Р·Р°РґР°С‡Рё Рё SMM",
            "keywords": ["РјР°СЂРєРµС‚РёРЅРі", "СЂРµРєР»Р°Рј", "РїРѕСЃС‚", "smm", "РєРѕРЅС‚РµРЅС‚", "СЃРѕС†СЃРµС‚Рё", "social", "campaign", "promotion", "advertising", "conversion", "seo", "crm"]
        },
        {
            "name": "РђРЅР°Р»РёС‚РёРєР°",
            "description": "РђРЅР°Р»РёС‚РёС‡РµСЃРєРёРµ Рё РѕС‚С‡РµС‚РЅС‹Рµ Р·Р°РґР°С‡Рё",
            "keywords": ["Р°РЅР°Р»РёС‚РёРє", "РѕС‚С‡РµС‚", "СЃС‚Р°С‚РёСЃС‚РёРє", "metric", "dashboard", "kpi", "analytics", "data", "metric", "report", "analysis"]
        },
        {
            "name": "Р’СЃС‚СЂРµС‡Рё",
            "description": "Р’СЃС‚СЂРµС‡Рё Рё РїРµСЂРµРіРѕРІРѕСЂС‹",
            "keywords": ["РІСЃС‚СЂРµС‡", "СЃРѕР±СЂР°РЅРёРµ", "Р·РІРѕРЅРѕРє", "РѕРЅР»Р°Р№РЅ", "meeting", "call", "conference", "presentation"]
        },
        {
            "name": "uncategorized",
            "description": "Р—Р°РґР°С‡Рё Р±РµР· РѕРїСЂРµРґРµР»РµРЅРЅРѕР№ РєР°С‚РµРіРѕСЂРёРё",
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
    """РџРѕР»СѓС‡Р°РµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РёР· Р‘Р” РёР»Рё СЃРѕР·РґР°РµС‚ РЅРѕРІРѕРіРѕ"""
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
    """РџРѕР»СѓС‡Р°РµС‚ С‡Р°С‚ РёР· Р‘Р” РёР»Рё СЃРѕР·РґР°РµС‚ РЅРѕРІС‹Р№"""
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
        # РћР±РЅРѕРІР»СЏРµРј РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ С‡Р°С‚Рµ, РµСЃР»Рё РёР·РјРµРЅРёР»Р°СЃСЊ
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
    РћС‚РїСЂР°РІР»СЏРµС‚ СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РЅРѕРІРѕРј РєРѕРјРјРµРЅС‚Р°СЂРёРё РІСЃРµРј СѓС‡Р°СЃС‚РЅРёРєР°Рј Р·Р°РґР°С‡Рё
    (СЃРѕР·РґР°С‚РµР»СЋ Рё РёСЃРїРѕР»РЅРёС‚РµР»СЏРј), РєСЂРѕРјРµ Р°РІС‚РѕСЂР° РєРѕРјРјРµРЅС‚Р°СЂРёСЏ.
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        comment_author = db.query(User).filter(User.id == comment_author_id).first()

        # РЎРѕР±РёСЂР°РµРј РІСЃРµС… СѓС‡Р°СЃС‚РЅРёРєРѕРІ Р·Р°РґР°С‡Рё (СЃРѕР·РґР°С‚РµР»СЊ + РёСЃРїРѕР»РЅРёС‚РµР»Рё)
        participants = set()

        # Р”РѕР±Р°РІР»СЏРµРј СЃРѕР·РґР°С‚РµР»СЏ Р·Р°РґР°С‡Рё
        if task.creator and task.creator.id != comment_author_id:
            participants.add(task.creator)

        # Р”РѕР±Р°РІР»СЏРµРј РІСЃРµС… РёСЃРїРѕР»РЅРёС‚РµР»РµР№
        for assignee in task.assignees:
            if assignee.id != comment_author_id:
                participants.add(assignee)

        # Р¤РѕСЂРјРёСЂСѓРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ
        notification = (
            f"рџ’¬ <b>РќРѕРІС‹Р№ РєРѕРјРјРµРЅС‚Р°СЂРёР№ Рє Р·Р°РґР°С‡Рµ</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
            f"<b>РђРІС‚РѕСЂ:</b> {comment_author.first_name or comment_author.username}\n"
            f"<b>РљРѕРјРјРµРЅС‚Р°СЂРёР№:</b> {comment_text[:200]}{'...' if len(comment_text) > 200 else ''}\n"
        )

        # РћС‚РїСЂР°РІР»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёСЏ РІСЃРµРј СѓС‡Р°СЃС‚РЅРёРєР°Рј
        for participant in participants:
            if participant.telegram_id and participant.telegram_id != -1:
                try:
                    webapp_url = build_webapp_url(mode="executor", user_id=participant.id, task_id=task.id)
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="рџ“± РћС‚РєСЂС‹С‚СЊ Р·Р°РґР°С‡Сѓ",
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
    РћС‚РїСЂР°РІР»СЏРµС‚ СѓРІРµРґРѕРјР»РµРЅРёРµ РёСЃРїРѕР»РЅРёС‚РµР»СЋ Рѕ РЅР°Р·РЅР°С‡РµРЅРёРё Р·Р°РґР°С‡Рё.
    Р•СЃР»Рё assignee РЅРµ СѓРєР°Р·Р°РЅ, Р±РµСЂРµС‚ РїРµСЂРІРѕРіРѕ РёСЃРїРѕР»РЅРёС‚РµР»СЏ РёР· task.assignees (РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё).
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        # Р•СЃР»Рё РёСЃРїРѕР»РЅРёС‚РµР»СЊ РЅРµ РїРµСЂРµРґР°РЅ, Р±РµСЂРµРј РёР· СЃРІСЏР·РµР№ Р·Р°РґР°С‡Рё
        if not assignee:
            if task.assignees:
                assignee = task.assignees[0]
            else:
                logger.warning(f"Task {task_id} has no assignees")
                return False

        # РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ Сѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РµСЃС‚СЊ telegram_id
        if assignee.telegram_id == -1 or assignee.telegram_id is None:
            logger.warning(f"User @{assignee.username} hasn't started a chat with the bot")
            return False

        # Р¤РѕСЂРјРёСЂСѓРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ
        notification = (
            f"рџ”” <b>Р’Р°Рј РЅР°Р·РЅР°С‡РµРЅР° РЅРѕРІР°СЏ Р·Р°РґР°С‡Р°</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {task.description}\n"

        # РџРѕРєР°Р·С‹РІР°РµРј РІСЃРµС… РёСЃРїРѕР»РЅРёС‚РµР»РµР№, РµСЃР»Рё РёС… РЅРµСЃРєРѕР»СЊРєРѕ
        if len(task.assignees) > 1:
            assignees_str = ", ".join([f"@{a.username}" for a in task.assignees if a.username])
            notification += f"<b>РСЃРїРѕР»РЅРёС‚РµР»Рё:</b> {assignees_str}\n"

        if task.due_date:
            notification += f"<b>РЎСЂРѕРє:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>РџСЂРёРѕСЂРёС‚РµС‚:</b> {task.priority}\n"
        notification += f"<b>РЎС‚Р°С‚СѓСЃ:</b> {task.status}\n"

        # РљРЅРѕРїРєРё
        webapp_url = build_webapp_url(mode="executor", user_id=assignee.id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ“± РћС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ],
            [
                InlineKeyboardButton(
                    text="в–¶пёЏ РќР°С‡Р°С‚СЊ РІС‹РїРѕР»РЅРµРЅРёРµ",
                    callback_data=f"task_start:{task.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="вњ… Р’С‹РїРѕР»РЅРµРЅРѕ",
                    callback_data=f"task_complete:{task.id}"
                )
            ]
        ])

        # РћС‚РїСЂР°РІР»СЏРµРј СЃРѕРѕР±С‰РµРЅРёРµ
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
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРѕРјР°РЅРґС‹ /start"""
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

        # Р¤Р»Р°Рі РїРµСЂРІРѕР№ Р°РІС‚РѕСЂРёР·Р°С†РёРё - РµСЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ Р±С‹Р» СЃРѕР·РґР°РЅ РїРѕ username Р±РµР· telegram_id
        is_first_auth = (user.telegram_id == -1 or user.telegram_id != message.from_user.id)

        # РћР±РЅРѕРІР»СЏРµРј telegram_id РµСЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ СЂР°РЅРµРµ Р±С‹Р» СЃРѕР·РґР°РЅ РїРѕ username
        if is_first_auth:
            user.telegram_id = message.from_user.id
            db.commit()
            logger.info(f"Updated telegram_id for user @{user.username} (ID: {user.id})")

        # РџСЂРѕРІРµСЂСЏРµРј РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹Рµ Р·Р°РґР°С‡Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
        pending_tasks = db.query(Task).join(Task.assignees).filter(
            User.id == user.id,
            Task.status.in_(["pending", "in_progress"])
        ).all()

        # РћС‚РїСЂР°РІР»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹С… Р·Р°РґР°С‡Р°С…
        if pending_tasks:
            for task in pending_tasks:
                task_webapp_url = build_webapp_url(mode="executor", user_id=user.id, task_id=task.id)
                task_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="рџ“± РћС‚РєСЂС‹С‚СЊ Р·Р°РґР°С‡Сѓ",
                            web_app=WebAppInfo(url=task_webapp_url)
                        )
                    ]
                ])

                notification = (
                    f"рџ“‹ <b>РЈ РІР°СЃ РµСЃС‚СЊ РЅРµР·Р°РІРµСЂС€РµРЅРЅР°СЏ Р·Р°РґР°С‡Р°</b>\n\n"
                    f"<b>{task.title}</b>\n"
                    f"РЎС‚Р°С‚СѓСЃ: {task.status}\n"
                    f"РџСЂРёРѕСЂРёС‚РµС‚: {task.priority}\n"
                )

                if task.due_date:
                    notification += f"РЎСЂРѕРє: {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

                await message.answer(notification, reply_markup=task_keyboard, parse_mode="HTML")

        webapp_url = build_webapp_url(mode="executor", user_id=user.id)

        # Р¤РѕСЂРјРёСЂСѓРµРј РїСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ
        if is_first_auth and pending_tasks:
            welcome_message = (
                f"вњ… Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ! Р’Р°Рј Р±С‹Р»Рѕ РЅР°Р·РЅР°С‡РµРЅРѕ {len(pending_tasks)} Р·Р°РґР°С‡.\n\n"
                "Р’С‹ РјРѕР¶РµС‚Рµ РѕС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ Р·Р°РґР°С‡ С‡РµСЂРµР· РєРЅРѕРїРєСѓ РЅРёР¶Рµ РёР»Рё РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РїРѕСЃС‚РѕСЏРЅРЅСѓСЋ РєРЅРѕРїРєСѓ РЅР°Рґ РєР»Р°РІРёР°С‚СѓСЂРѕР№."
            )
        elif pending_tasks:
            welcome_message = (
                f"вњ… РЎ РІРѕР·РІСЂР°С‰РµРЅРёРµРј! РЈ РІР°СЃ {len(pending_tasks)} РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹С… Р·Р°РґР°С‡.\n\n"
                "РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ РёР»Рё РїРѕСЃС‚РѕСЏРЅРЅСѓСЋ РєРЅРѕРїРєСѓ РґР»СЏ РґРѕСЃС‚СѓРїР° Рє РїР°РЅРµР»Рё Р·Р°РґР°С‡."
            )
        else:
            welcome_message = (
                "вњ… РћС‚Р»РёС‡РЅРѕ! РўРµРїРµСЂСЊ РІС‹ Р±СѓРґРµС‚Рµ РїРѕР»СѓС‡Р°С‚СЊ СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ Р·Р°РґР°С‡Р°С….\n\n"
                "рџ¤– TaskBridge РёСЃРїРѕР»СЊР·СѓРµС‚ AI РґР»СЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ РёР·РІР»РµС‡РµРЅРёСЏ Р·Р°РґР°С‡ РёР· С‡Р°С‚РѕРІ.\n\n"
                "Р”РѕР±Р°РІСЊС‚Рµ РјРµРЅСЏ РІ РіСЂСѓРїРїРѕРІРѕР№ С‡Р°С‚, С‡С‚РѕР±С‹ СЏ РЅР°С‡Р°Р» Р°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ СЃРѕРѕР±С‰РµРЅРёСЏ.\n\n"
                "РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ \"рџ“± РџР°РЅРµР»СЊ Р·Р°РґР°С‡\" РґР»СЏ Р±С‹СЃС‚СЂРѕРіРѕ РґРѕСЃС‚СѓРїР° Рє РІР°С€РёРј Р·Р°РґР°С‡Р°Рј."
            )

        # Inline РєРЅРѕРїРєР° РґР»СЏ РѕРґРЅРѕСЂР°Р·РѕРІРѕРіРѕ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ“± РћС‚РєСЂС‹С‚СЊ РјРѕСЋ РїР°РЅРµР»СЊ Р·Р°РґР°С‡",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ],
            [
                InlineKeyboardButton(
                    text="рџ“§ Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊ Email",
                    callback_data="register_email"
                ),
                InlineKeyboardButton(
                    text="рџ’¬ Р§Р°С‚ РїРѕРґРґРµСЂР¶РєРё",
                    callback_data="support_start"
                )
            ]
        ])

        # РџРѕСЃС‚РѕСЏРЅРЅР°СЏ РєР»Р°РІРёР°С‚СѓСЂР° СЃ РєРЅРѕРїРєРѕР№ Р±С‹СЃС‚СЂРѕРіРѕ РґРѕСЃС‚СѓРїР°
        reply_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="рџ“± РџР°РЅРµР»СЊ Р·Р°РґР°С‡",
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

        # РћС‚РїСЂР°РІР»СЏРµРј РѕС‚РґРµР»СЊРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ СЃ РїРѕСЃС‚РѕСЏРЅРЅРѕР№ РєР»Р°РІРёР°С‚СѓСЂРѕР№
        await message.answer(
            "РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ РґР»СЏ Р±С‹СЃС‚СЂРѕРіРѕ РґРѕСЃС‚СѓРїР°:",
            reply_markup=reply_keyboard
        )

    except Exception as e:
        logger.error(f"Error in /start command: {e}", exc_info=True)
        await message.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ.")
    finally:
        db.close()


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРѕРјР°РЅРґС‹ /panel - РѕС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ Р·Р°РґР°С‡"""
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

        webapp_url = build_webapp_url(mode="executor", user_id=user.id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ“± РћС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ Р·Р°РґР°С‡",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ])

        await message.answer("РќР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ РґР»СЏ РґРѕСЃС‚СѓРїР° Рє РїР°РЅРµР»Рё Р·Р°РґР°С‡:", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in /panel command: {e}", exc_info=True)
        await message.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ.")
    finally:
        db.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРѕРјР°РЅРґС‹ /help"""
    help_text = (
        "рџ“‹ <b>TaskBridge - AI-СѓРїСЂР°РІР»РµРЅРёРµ Р·Р°РґР°С‡Р°РјРё</b>\n\n"
        "<b>РљРѕРјР°РЅРґС‹:</b>\n"
        "/start - РќР°С‡Р°С‚СЊ СЂР°Р±РѕС‚Сѓ Рё РѕС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ Р·Р°РґР°С‡\n"
        "/panel - РћС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ Р·Р°РґР°С‡\n"
        "/help - РџРѕРєР°Р·Р°С‚СЊ СЃРїСЂР°РІРєСѓ\n\n"
        "<b>РљР°Рє РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ:</b>\n"
        "1. Р”РѕР±Р°РІСЊС‚Рµ Р±РѕС‚Р° РІ РіСЂСѓРїРїРѕРІРѕР№ С‡Р°С‚\n"
        "2. РџРёС€РёС‚Рµ СЃРѕРѕР±С‰РµРЅРёСЏ СЃ Р·Р°РґР°С‡Р°РјРё, РЅР°РїСЂРёРјРµСЂ:\n"
        "   вЂў <i>@alex СЃРґРµР»Р°Р№ РѕС‚С‡РµС‚ РґРѕ Р·Р°РІС‚СЂР°</i>\n"
        "   вЂў <i>РЎР°С€Р°, СЃСЂРѕС‡РЅРѕ РёСЃРїСЂР°РІСЊ Р±Р°Рі Рє РІРµС‡РµСЂСѓ</i>\n"
        "3. Р‘РѕС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РёР·РІР»РµС‡РµС‚ Р·Р°РґР°С‡Сѓ СЃ РїРѕРјРѕС‰СЊСЋ AI\n"
        "4. РџРѕРґС‚РІРµСЂРґРёС‚Рµ Р·Р°РґР°С‡Сѓ РёР»Рё РѕС‚СЂРµРґР°РєС‚РёСЂСѓР№С‚Рµ РµС‘\n"
        "5. РСЃРїРѕР»РЅРёС‚РµР»СЊ РїРѕР»СѓС‡РёС‚ СѓРІРµРґРѕРјР»РµРЅРёРµ\n\n"
        "рџ¤– <b>AI Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РѕРїСЂРµРґРµР»СЏРµС‚:</b>\n"
        "вЂў РћРїРёСЃР°РЅРёРµ Р·Р°РґР°С‡Рё\n"
        "вЂў РСЃРїРѕР»РЅРёС‚РµР»СЏ (@username РёР»Рё РёРјСЏ)\n"
        "вЂў РЎСЂРѕРє РІС‹РїРѕР»РЅРµРЅРёСЏ (РґРѕ РІРµС‡РµСЂР°, РґРѕ РѕР±РµРґР°, РєРѕРЅРєСЂРµС‚РЅС‹Рµ РґР°С‚С‹)\n"
        "вЂў РџСЂРёРѕСЂРёС‚РµС‚\n\n"
        "рџ“§ <b>Р РµРіРёСЃС‚СЂР°С†РёСЏ Email Р°РєРєР°СѓРЅС‚Р°:</b>\n"
        "1. РќР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ \"рџ“§ Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊ Email\" РІ /start\n"
        "2. Р’РІРµРґРёС‚Рµ РІР°С€ email Р°РґСЂРµСЃ (РЅР°РїСЂРёРјРµСЂ: name@gmail.com)\n"
        "3. РџРѕР»СѓС‡РёС‚Рµ РїР°СЂРѕР»СЊ РїСЂРёР»РѕР¶РµРЅРёСЏ:\n\n"
        "   <b>Gmail:</b>\n"
        "   вЂў Р’РєР»СЋС‡РёС‚Рµ РґРІСѓС…С„Р°РєС‚РѕСЂРЅСѓСЋ Р°СѓС‚РµРЅС‚РёС„РёРєР°С†РёСЋ РІ РЅР°СЃС‚СЂРѕР№РєР°С… Google\n"
        "   вЂў РџРµСЂРµР№РґРёС‚Рµ: myaccount.google.com/apppasswords\n"
        "   вЂў РЎРѕР·РґР°Р№С‚Рµ РїР°СЂРѕР»СЊ РїСЂРёР»РѕР¶РµРЅРёСЏ РґР»СЏ \"РџРѕС‡С‚Р°\"\n\n"
        "   <b>Yandex:</b>\n"
        "   вЂў Р’РєР»СЋС‡РёС‚Рµ IMAP РІ РЅР°СЃС‚СЂРѕР№РєР°С… РїРѕС‡С‚С‹\n"
        "   вЂў РџРµСЂРµР№РґРёС‚Рµ: id.yandex.ru/security/app-passwords\n"
        "   вЂў РЎРѕР·РґР°Р№С‚Рµ РїР°СЂРѕР»СЊ РґР»СЏ РїРѕС‡С‚РѕРІРѕР№ РїСЂРѕРіСЂР°РјРјС‹\n\n"
        "   <b>Outlook/Hotmail:</b>\n"
        "   вЂў Р’РєР»СЋС‡РёС‚Рµ РґРІСѓС…С„Р°РєС‚РѕСЂРЅСѓСЋ Р°СѓС‚РµРЅС‚РёС„РёРєР°С†РёСЋ\n"
        "   вЂў РџРµСЂРµР№РґРёС‚Рµ: account.microsoft.com/security\n"
        "   вЂў РЎРѕР·РґР°Р№С‚Рµ РїР°СЂРѕР»СЊ РїСЂРёР»РѕР¶РµРЅРёСЏ\n\n"
        "   <b>Mail.ru:</b>\n"
        "   вЂў Р’РєР»СЋС‡РёС‚Рµ IMAP РІ РЅР°СЃС‚СЂРѕР№РєР°С… РїРѕС‡С‚С‹\n"
        "   вЂў РџРµСЂРµР№РґРёС‚Рµ: e.mail.ru/settings/security\n"
        "   вЂў РЎРѕР·РґР°Р№С‚Рµ РїР°СЂРѕР»СЊ РґР»СЏ РІРЅРµС€РЅРёС… РїСЂРёР»РѕР¶РµРЅРёР№\n\n"
        "4. Р’СЃС‚Р°РІСЊС‚Рµ РїРѕР»СѓС‡РµРЅРЅС‹Р№ РїР°СЂРѕР»СЊ РІ Р±РѕС‚\n"
        "5. Р“РѕС‚РѕРІРѕ! РџРёСЃСЊРјР° Р±СѓРґСѓС‚ РїСЂРѕРІРµСЂСЏС‚СЊСЃСЏ РєР°Р¶РґС‹Рµ 10 РјРёРЅСѓС‚\n\n"
        "рџ’Ў Р‘РѕС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРѕР·РґР°СЃС‚ Р·Р°РґР°С‡Рё РёР· РІС…РѕРґСЏС‰РёС… РїРёСЃРµРј СЃ РїРѕРјРѕС‰СЊСЋ AI"
    )

    await message.answer(help_text, parse_mode="HTML")




@router.callback_query(F.data.startswith("task_start:"))
async def handle_task_start(callback: CallbackQuery):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РЅР°С‡Р°Р»Р° РІС‹РїРѕР»РЅРµРЅРёСЏ Р·Р°РґР°С‡Рё"""
    db = get_db_session()

    try:
        task_id = int(callback.data.split(":")[1])
        task = db.query(Task).filter(Task.id == task_id).first()

        if not task:
            await callback.answer("Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return

        if task.status == "completed":
            await callback.answer("Р—Р°РґР°С‡Р° СѓР¶Рµ РІС‹РїРѕР»РЅРµРЅР°", show_alert=True)
            return

        
        task.status = "in_progress"
        db.commit()

        
        notification = (
            f"в–¶пёЏ <b>Р—Р°РґР°С‡Р° РІ РїСЂРѕС†РµСЃСЃРµ РІС‹РїРѕР»РЅРµРЅРёСЏ</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {task.description}\n"

        if task.due_date:
            notification += f"<b>РЎСЂРѕРє:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>РџСЂРёРѕСЂРёС‚РµС‚:</b> {task.priority}\n"
        notification += f"<b>РЎС‚Р°С‚СѓСЃ:</b> РІ РїСЂРѕС†РµСЃСЃРµ\n"
        notification += f"\nрџ“Ћ РњРѕР¶РµС‚Рµ РѕС‚РїСЂР°РІРёС‚СЊ С„РѕС‚Рѕ/С„Р°Р№Р»С‹ РєР°Рє РѕС‚С‡С‘С‚"

        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="вњ… Р’С‹РїРѕР»РЅРµРЅРѕ",
                    callback_data=f"task_complete:{task.id}"
                )
            ]
        ])

        await callback.message.edit_text(notification, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("РЎС‚Р°С‚СѓСЃ РёР·РјРµРЅС‘РЅ РЅР° 'РІ РїСЂРѕС†РµСЃСЃРµ' вњ…")

    except Exception as e:
        logger.error(f"Error starting task: {e}", exc_info=True)
        await callback.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("assign_user:"))
async def handle_assign_user(callback: CallbackQuery):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РІС‹Р±РѕСЂР° РёСЃРїРѕР»РЅРёС‚РµР»СЏ РёР· РіСЂСѓРїРїРѕРІРѕРіРѕ С‡Р°С‚Р°"""
    db = get_db_session()

    try:
        # РџР°СЂСЃРёРј callback data: assign_user:{pending_task_id}:{telegram_user_id}
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("РћС€РёР±РєР°: РЅРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚ РґР°РЅРЅС‹С…", show_alert=True)
            return

        pending_task_id = int(parts[1])
        selected_telegram_id = int(parts[2])

        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ callback РІС‹Р·РІР°РЅ СЃРѕР·РґР°С‚РµР»РµРј Р·Р°РґР°С‡Рё
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()
        if not pending_task:
            await callback.answer("Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return

        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        if not creator or creator.telegram_id != callback.from_user.id:
            await callback.answer("РўРѕР»СЊРєРѕ СЃРѕР·РґР°С‚РµР»СЊ Р·Р°РґР°С‡Рё РјРѕР¶РµС‚ РІС‹Р±СЂР°С‚СЊ РёСЃРїРѕР»РЅРёС‚РµР»СЏ", show_alert=True)
            return

        # РќР°С…РѕРґРёРј РёР»Рё СЃРѕР·РґР°РµРј РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ-РёСЃРїРѕР»РЅРёС‚РµР»СЏ
        assignee = db.query(User).filter(User.telegram_id == selected_telegram_id).first()
        if not assignee:
            # РЎРѕР·РґР°РµРј РІСЂРµРјРµРЅРЅРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (Р±СѓРґРµС‚ РѕР±РЅРѕРІР»РµРЅ РєРѕРіРґР° РѕРЅ Р·Р°РїСѓСЃС‚РёС‚ Р±РѕС‚Р°)
            assignee = User(
                telegram_id=selected_telegram_id,
                username=callback.message.reply_markup.inline_keyboard[0][0].text,  # Р‘РµСЂРµРј РёРјСЏ РёР· РєРЅРѕРїРєРё
                is_bot=False
            )
            db.add(assignee)
            db.commit()
            db.refresh(assignee)

        # РћР±РЅРѕРІР»СЏРµРј pending_task СЃ РІС‹Р±СЂР°РЅРЅС‹Рј РёСЃРїРѕР»РЅРёС‚РµР»РµРј
        pending_task.assignee_usernames = [assignee.username] if assignee.username else []
        pending_task.assignee_username = assignee.username
        db.commit()

        # РЈРґР°Р»СЏРµРј СЃРѕРѕР±С‰РµРЅРёРµ СЃ РєРЅРѕРїРєР°РјРё РёР· РіСЂСѓРїРїС‹
        try:
            await callback.message.delete()
        except:
            pass

        # РћС‚РїСЂР°РІР»СЏРµРј РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ Р’ Р›РР§РќР«Р• РЎРћРћР‘Р©Р•РќРРЇ СЃРѕР·РґР°С‚РµР»СЋ
        assignee_name = assignee.first_name or assignee.username or f"User {assignee.telegram_id}"

        confirmation_text = (
            f"вњ… <b>РСЃРїРѕР»РЅРёС‚РµР»СЊ РІС‹Р±СЂР°РЅ!</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {pending_task.title}\n"
            f"<b>РСЃРїРѕР»РЅРёС‚РµР»СЊ:</b> {assignee_name}\n"
        )

        if pending_task.description:
            confirmation_text += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {pending_task.description}\n"

        if pending_task.due_date:
            confirmation_text += f"<b>РЎСЂРѕРє:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        confirmation_text += f"<b>РџСЂРёРѕСЂРёС‚РµС‚:</b> {pending_task.priority}\n\n"
        confirmation_text += "РџРѕРґС‚РІРµСЂРґРёС‚Рµ СЃРѕР·РґР°РЅРёРµ Р·Р°РґР°С‡Рё:"

        # РљРЅРѕРїРєРё РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="вњ… РџРѕРґС‚РІРµСЂРґРёС‚СЊ",
                    callback_data=f"confirm_task:{pending_task.id}"
                ),
                InlineKeyboardButton(
                    text="вќЊ РћС‚РєР»РѕРЅРёС‚СЊ",
                    callback_data=f"reject_task:{pending_task.id}"
                )
            ]
        ])

        # РћС‚РїСЂР°РІР»СЏРµРј РІ Р»РёС‡РЅС‹Рµ СЃРѕРѕР±С‰РµРЅРёСЏ
        await callback.bot.send_message(
            chat_id=creator.telegram_id,
            text=confirmation_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer(f"РСЃРїРѕР»РЅРёС‚РµР»СЊ РЅР°Р·РЅР°С‡РµРЅ: {assignee_name}")
        logger.info(f"User {assignee.telegram_id} assigned to pending_task {pending_task.id}")

    except TelegramForbiddenError:
        await callback.answer(
            "РќРµ РјРѕРіСѓ РѕС‚РїСЂР°РІРёС‚СЊ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РІ Р»РёС‡РЅС‹Рµ СЃРѕРѕР±С‰РµРЅРёСЏ. РќР°С‡РЅРёС‚Рµ С‡Р°С‚ СЃ Р±РѕС‚РѕРј РєРѕРјР°РЅРґРѕР№ /start",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Error in assign_user callback: {e}", exc_info=True)
        await callback.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("confirm_task:"))
async def handle_confirm_task(callback: CallbackQuery):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ Р·Р°РґР°С‡Рё"""
    db = get_db_session()

    try:
        pending_task_id = int(callback.data.split(":")[1])
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()

        if not pending_task:
            await callback.answer("Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return

        if pending_task.status != "pending":
            await callback.answer("Р—Р°РґР°С‡Р° СѓР¶Рµ РѕР±СЂР°Р±РѕС‚Р°РЅР°", show_alert=True)
            return

        # РћРїСЂРµРґРµР»СЏРµРј РёСЃРїРѕР»РЅРёС‚РµР»РµР№ (РїРѕРґРґРµСЂР¶РєР° РЅРѕРІРѕРіРѕ Рё СЃС‚Р°СЂРѕРіРѕ С„РѕСЂРјР°С‚Р°)
        assignee_usernames = pending_task.assignee_usernames or []
        if not assignee_usernames and pending_task.assignee_username:
            assignee_usernames = [pending_task.assignee_username]

        # РљР»Р°СЃСЃРёС„РёС†РёСЂСѓРµРј Р·Р°РґР°С‡Сѓ
        category_id = classify_task(pending_task.description or pending_task.title, db)

        # Р•СЃР»Рё РґРµРґР»Р°Р№РЅ РЅРµ СѓРєР°Р·Р°РЅ, СЃС‚Р°РІРёРј +24 С‡Р°СЃР° РѕС‚ С‚РµРєСѓС‰РµРіРѕ РІСЂРµРјРµРЅРё
        due_date = pending_task.due_date
        if not due_date:
            from datetime import datetime, timedelta
            due_date = datetime.now() + timedelta(hours=24)

        # РЎРѕР·РґР°РµРј Р·Р°РґР°С‡Сѓ
        task = Task(
            message_id=pending_task.message_id,
            category_id=category_id,
            created_by=pending_task.created_by_id,  # РЎРѕС…СЂР°РЅСЏРµРј СЃРѕР·РґР°С‚РµР»СЏ
            title=pending_task.title,
            description=pending_task.description,
            status="pending",
            priority=pending_task.priority,
            due_date=due_date
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        # РќР°Р·РЅР°С‡Р°РµРј РёСЃРїРѕР»РЅРёС‚РµР»РµР№ (many-to-many)
        if assignee_usernames:
            for username in assignee_usernames:
                assignee = await get_or_create_user_by_username(db, username)
                task.assignees.append(assignee)
            db.commit()

        # РћС‚РјРµС‡Р°РµРј pending task РєР°Рє РїРѕРґС‚РІРµСЂР¶РґРµРЅРЅС‹Р№
        pending_task.status = "confirmed"
        db.commit()

        # РЈРІРµРґРѕРјР»СЏРµРј РІСЃРµС… РёСЃРїРѕР»РЅРёС‚РµР»РµР№
        if task.assignees:
            for assignee in task.assignees:
                # РћС‚РїСЂР°РІР»СЏРµРј Р»РёС‡РЅРѕРµ СѓРІРµРґРѕРјР»РµРЅРёРµ РєРѕРЅРєСЂРµС‚РЅРѕРјСѓ РёСЃРїРѕР»РЅРёС‚РµР»СЋ
                notification_sent = await notify_assigned_user(callback.bot, task.id, db, assignee=assignee)

                # Р•СЃР»Рё СѓРІРµРґРѕРјР»РµРЅРёРµ РЅРµ РѕС‚РїСЂР°РІР»РµРЅРѕ (РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°С‡Р°Р» С‡Р°С‚ СЃ Р±РѕС‚РѕРј)
                if not notification_sent and assignee.username:
                    try:
                        await callback.bot.send_message(
                            chat_id=pending_task.chat_id,
                            text=f"@{assignee.username}, РІР°Рј РЅР°Р·РЅР°С‡РµРЅР° Р·Р°РґР°С‡Р°: <b>{task.title}</b>\n\n",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send group notification: {e}")

        
        creator = db.query(User).filter(User.id == pending_task.created_by_id).first()
        webapp_url = build_webapp_url(mode="manager", user_id=creator.id) if creator else build_webapp_url(mode=None)

        
        manager_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ“± РћС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ СѓРїСЂР°РІР»РµРЅРёСЏ",
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ])

        # Р¤РѕСЂРјРёСЂСѓРµРј С‚РµРєСЃС‚ СЃ РёСЃРїРѕР»РЅРёС‚РµР»СЏРјРё
        confirmation_msg = (
            f"вњ… <b>Р—Р°РґР°С‡Р° РїРѕРґС‚РІРµСЂР¶РґРµРЅР° Рё РѕС‚РїСЂР°РІР»РµРЅР°!</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
        )

        if task.assignees:
            if len(task.assignees) == 1:
                confirmation_msg += f"<b>РСЃРїРѕР»РЅРёС‚РµР»СЊ:</b> @{task.assignees[0].username}\n"
            else:
                assignees_str = ", ".join([f"@{a.username}" for a in task.assignees if a.username])
                confirmation_msg += f"<b>РСЃРїРѕР»РЅРёС‚РµР»Рё:</b> {assignees_str}\n"
        else:
            confirmation_msg += f"<b>РСЃРїРѕР»РЅРёС‚РµР»СЊ:</b> РЅРµ СѓРєР°Р·Р°РЅ\n"

        confirmation_msg += f"<b>РЎСЂРѕРє:</b> {task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'РЅРµ СѓРєР°Р·Р°РЅ'}\n"
        confirmation_msg += f"<b>РџСЂРёРѕСЂРёС‚РµС‚:</b> {task.priority}"

        await callback.message.edit_text(
            confirmation_msg,
            reply_markup=manager_keyboard,
            parse_mode="HTML"
        )

        await callback.answer("Р—Р°РґР°С‡Р° СЃРѕР·РґР°РЅР°! вњ…")

    except Exception as e:
        logger.error(f"Error confirming task: {e}", exc_info=True)
        await callback.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("reject_task:"))
async def handle_reject_task(callback: CallbackQuery):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РѕС‚РєР»РѕРЅРµРЅРёСЏ Р·Р°РґР°С‡Рё"""
    db = get_db_session()

    try:
        pending_task_id = int(callback.data.split(":")[1])
        pending_task = db.query(PendingTask).filter(PendingTask.id == pending_task_id).first()

        if not pending_task:
            await callback.answer("Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return

        if pending_task.status != "pending":
            await callback.answer("Р—Р°РґР°С‡Р° СѓР¶Рµ РѕР±СЂР°Р±РѕС‚Р°РЅР°", show_alert=True)
            return

        pending_task.status = "rejected"
        db.commit()

        await callback.message.edit_text(
            f"вќЊ <b>Р—Р°РґР°С‡Р° РѕС‚РєР»РѕРЅРµРЅР°</b>\n\n"
            f"Р—Р°РґР°С‡Р°: {pending_task.title}",
            parse_mode="HTML"
        )

        await callback.answer("Р—Р°РґР°С‡Р° РѕС‚РєР»РѕРЅРµРЅР°")

    except Exception as e:
        logger.error(f"Error rejecting task: {e}", exc_info=True)
        await callback.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("task_complete:"))
async def handle_task_complete(callback: CallbackQuery):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РѕС‚РјРµС‚РєРё Р·Р°РґР°С‡Рё РєР°Рє РІС‹РїРѕР»РЅРµРЅРЅРѕР№"""
    db = get_db_session()

    try:
        task_id = int(callback.data.split(":")[1])
        task = db.query(Task).filter(Task.id == task_id).first()

        if not task:
            await callback.answer("Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return

        if task.status == "completed":
            await callback.answer("Р—Р°РґР°С‡Р° СѓР¶Рµ РІС‹РїРѕР»РЅРµРЅР°", show_alert=True)
            return

        task.status = "completed"
        db.commit()

        await callback.message.edit_text(
            f"вњ… <b>Р—Р°РґР°С‡Р° РІС‹РїРѕР»РЅРµРЅР°!</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
            f"<b>Р—Р°РІРµСЂС€РµРЅР°:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="HTML"
        )

        await callback.answer("РћС‚Р»РёС‡РЅРѕ! Р—Р°РґР°С‡Р° РѕС‚РјРµС‡РµРЅР° РєР°Рє РІС‹РїРѕР»РЅРµРЅРЅР°СЏ вњ…")

    except Exception as e:
        logger.error(f"Error completing task: {e}", exc_info=True)
        await callback.answer("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°", show_alert=True)
    finally:
        db.close()


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message(message: Message):
    """РћР±СЂР°Р±РѕС‚С‡РёРє СЃРѕРѕР±С‰РµРЅРёР№ РёР· РіСЂСѓРїРїРѕРІС‹С… С‡Р°С‚РѕРІ СЃ AI-РёР·РІР»РµС‡РµРЅРёРµРј Р·Р°РґР°С‡"""
    db = get_db_session()

    try:

        if message.from_user.is_bot:
            return

        # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј/РѕР±РЅРѕРІР»СЏРµРј С‡Р°С‚ РІ Р±Р°Р·Рµ РґР°РЅРЅС‹С…
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

        
        logger.info(f"Analyzing message: {message.text[:50]}...")
        ai_result = await analyze_message(message.text, use_ai=True)

        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in message")
            return

        
        message_obj.has_task = True
        db.commit()

        task_data = ai_result.get("task", {})

        # Р›РѕРіРёСЂСѓРµРј РґР°РЅРЅС‹Рµ РѕС‚ AI
        logger.info(f"Task data from AI: {task_data}")

        # РР·РІР»РµРєР°РµРј СЃРїРёСЃРѕРє РёСЃРїРѕР»РЅРёС‚РµР»РµР№ (РЅРѕРІС‹Р№ С„РѕСЂРјР°С‚) РёР»Рё fallback РЅР° СЃС‚Р°СЂС‹Р№
        assignee_usernames = task_data.get("assignee_usernames", [])
        if not assignee_usernames:
            # Fallback РЅР° СЃС‚Р°СЂРѕРµ РїРѕР»Рµ РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
            old_assignee = task_data.get("assignee_username")
            if old_assignee:
                assignee_usernames = [old_assignee]

        logger.info(f"Assignee usernames from AI: {assignee_usernames}")

        # РќРћР’РђРЇ Р›РћР“РРљРђ: Р•СЃР»Рё РЅРµС‚ РёСЃРїРѕР»РЅРёС‚РµР»СЏ - СЃРїСЂР°С€РёРІР°РµРј РІ Р“Р РЈРџРџРћР’РћРњ С‡Р°С‚Рµ
        if not assignee_usernames:
            logger.info("No assignee found - asking in private chat")

            try:
                # РџРѕР»СѓС‡Р°РµРј СѓС‡Р°СЃС‚РЅРёРєРѕРІ С‡Р°С‚Р°
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

                # Р”РѕР±Р°РІР»СЏРµРј Р°РІС‚РѕСЂР° СЃРѕРѕР±С‰РµРЅРёСЏ РµСЃР»Рё РµРіРѕ РЅРµС‚ РІ СЃРїРёСЃРєРµ
                author_in_list = any(m['id'] == message.from_user.id for m in chat_members)
                if not author_in_list and not message.from_user.is_bot:
                    chat_members.append({
                        'id': message.from_user.id,
                        'username': message.from_user.username,
                        'first_name': message.from_user.first_name
                    })

                if not chat_members:
                    logger.warning("No chat members found, cannot ask for assignee")
                    # РџСЂРѕРїСѓСЃРєР°РµРј СЃРѕР·РґР°РЅРёРµ Р·Р°РґР°С‡Рё РµСЃР»Рё РЅРµС‚ СѓС‡Р°СЃС‚РЅРёРєРѕРІ
                    return

                # РЎРѕР·РґР°РµРј РІСЂРµРјРµРЅРЅС‹Р№ pending task Р‘Р•Р— РёСЃРїРѕР»РЅРёС‚РµР»СЏ
                # РЅРѕ СЃРѕС…СЂР°РЅСЏРµРј РµРіРѕ РґР»СЏ РїРѕСЃР»РµРґСѓСЋС‰РµРіРѕ РІС‹Р±РѕСЂР°
                pending_task = PendingTask(
                    message_id=message_obj.id,
                    chat_id=message.chat.id,
                    created_by_id=user.id,
                    title=task_data.get("title", "Р‘РµР· РЅР°Р·РІР°РЅРёСЏ"),
                    description=task_data.get("description"),
                    assignee_usernames=None,  # Р‘СѓРґРµС‚ РЅР°Р·РЅР°С‡РµРЅ РїРѕСЃР»Рµ РІС‹Р±РѕСЂР°
                    due_date=task_data.get("due_date_parsed"),
                    priority=task_data.get("priority", "normal"),
                    status="pending"
                )

                db.add(pending_task)
                db.commit()
                db.refresh(pending_task)

                # Р¤РѕСЂРјРёСЂСѓРµРј СЃРѕРѕР±С‰РµРЅРёРµ СЃ РєРЅРѕРїРєР°РјРё РІС‹Р±РѕСЂР° РёСЃРїРѕР»РЅРёС‚РµР»СЏ Р’ Р“Р РЈРџРџР•
                ask_text = (
                    f"рџ¤– <b>РћР±РЅР°СЂСѓР¶РµРЅР° Р·Р°РґР°С‡Р° Р±РµР· РёСЃРїРѕР»РЅРёС‚РµР»СЏ</b>\n\n"
                    f"<b>Р—Р°РґР°С‡Р°:</b> {pending_task.title}\n"
                )

                if pending_task.description:
                    ask_text += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {pending_task.description}\n"

                ask_text += f"\n{message.from_user.first_name}, РєРѕРјСѓ РЅР°Р·РЅР°С‡РёС‚СЊ СЌС‚Сѓ Р·Р°РґР°С‡Сѓ?"

                # РЎРѕР·РґР°РµРј РєРЅРѕРїРєРё СЃ СѓС‡Р°СЃС‚РЅРёРєР°РјРё (РјР°РєСЃРёРјСѓРј 2 РІ СЂСЏРґ)
                buttons = []
                row = []
                for member in chat_members:
                    display_name = member['first_name'] or member['username'] or f"User {member['id']}"
                    row.append(InlineKeyboardButton(
                        text=display_name[:20],  # РћРіСЂР°РЅРёС‡РёРІР°РµРј РґР»РёРЅСѓ
                        callback_data=f"assign_user:{pending_task.id}:{member['id']}"
                    ))

                    if len(row) == 2:
                        buttons.append(row)
                        row = []

                # Р”РѕР±Р°РІР»СЏРµРј РѕСЃС‚Р°С‚РѕРє
                if row:
                    buttons.append(row)

                # РљРЅРѕРїРєР° РѕС‚РјРµРЅС‹
                buttons.append([
                    InlineKeyboardButton(
                        text="вќЊ РћС‚РјРµРЅРёС‚СЊ Р·Р°РґР°С‡Сѓ",
                        callback_data=f"reject_task:{pending_task.id}"
                    )
                ])

                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

                # РћС‚РїСЂР°РІР»СЏРµРј РџР РЇРњРћ Р’ Р“Р РЈРџРџРЈ
                await message.bot.send_message(
                    chat_id=message.from_user.id,
                    text=ask_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

                logger.info(f"Sent assignee selection to private chat for user {message.from_user.id}")
                return  # Р’С‹С…РѕРґРёРј, РЅРµ СЃРѕР·РґР°РµРј РѕР±С‹С‡РЅС‹Р№ pending task

            except Exception as e:
                logger.error(f"Error asking for assignee: {e}", exc_info=True)
                # Р•СЃР»Рё РЅРµ СЃРјРѕРіР»Рё СЃРїСЂРѕСЃРёС‚СЊ - СЃРѕР·РґР°РµРј Р·Р°РґР°С‡Сѓ Р±РµР· РёСЃРїРѕР»РЅРёС‚РµР»СЏ
                assignee_usernames = []

        # РЎРѕР·РґР°РµРј pending task (С‚РѕР»СЊРєРѕ РµСЃР»Рё РёСЃРїРѕР»РЅРёС‚РµР»СЊ РЈР–Р• РёР·РІРµСЃС‚РµРЅ)
        pending_task = PendingTask(
            message_id=message_obj.id,
            chat_id=message.chat.id,
            created_by_id=user.id,
            title=task_data.get("title", "Р‘РµР· РЅР°Р·РІР°РЅРёСЏ"),
            description=task_data.get("description"),
            assignee_usernames=assignee_usernames if assignee_usernames else None,
            assignee_username=assignee_usernames[0] if assignee_usernames else None,  # Р”Р»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
            due_date=task_data.get("due_date_parsed"),
            priority=task_data.get("priority", "normal"),
            status="pending"
        )

        logger.info(f"Created pending task with assignees: {pending_task.assignee_usernames}")

        db.add(pending_task)
        db.commit()
        db.refresh(pending_task)

        # Р¤РѕСЂРјРёСЂСѓРµРј С‚РµРєСЃС‚ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ
        confirmation_text = (
            f"рџ¤– <b>AI РѕР±РЅР°СЂСѓР¶РёР» Р·Р°РґР°С‡Сѓ!</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {pending_task.title}\n"
        )

        if pending_task.description and pending_task.description != pending_task.title:
            confirmation_text += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {pending_task.description}\n"

        # РџРѕРєР°Р·С‹РІР°РµРј РІСЃРµС… РёСЃРїРѕР»РЅРёС‚РµР»РµР№
        if pending_task.assignee_usernames:
            if len(pending_task.assignee_usernames) == 1:
                confirmation_text += f"<b>РСЃРїРѕР»РЅРёС‚РµР»СЊ:</b> @{pending_task.assignee_usernames[0]}\n"
            else:
                assignees_str = ", ".join([f"@{u}" for u in pending_task.assignee_usernames])
                confirmation_text += f"<b>РСЃРїРѕР»РЅРёС‚РµР»Рё:</b> {assignees_str}\n"
        elif pending_task.assignee_username:
            # Fallback РЅР° СЃС‚Р°СЂРѕРµ РїРѕР»Рµ
            confirmation_text += f"<b>РСЃРїРѕР»РЅРёС‚РµР»СЊ:</b> @{pending_task.assignee_username}\n"

        if pending_task.due_date:
            confirmation_text += f"<b>РЎСЂРѕРє:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        confirmation_text += f"<b>РџСЂРёРѕСЂРёС‚РµС‚:</b> {pending_task.priority}\n\n"
        confirmation_text += "РџРѕРґС‚РІРµСЂРґРёС‚Рµ СЃРѕР·РґР°РЅРёРµ Р·Р°РґР°С‡Рё:"

       
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="вњ… РџРѕРґС‚РІРµСЂРґРёС‚СЊ",
                    callback_data=f"confirm_task:{pending_task.id}"
                ),
                InlineKeyboardButton(
                    text="вќЊ РћС‚РєР»РѕРЅРёС‚СЊ",
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
        logger.warning(f"User hasn't started the bot, cannot send confirmation in private chat")
    except Exception as e:
        logger.error(f"Error handling group message: {e}", exc_info=True)
    finally:
        db.close()


@router.message(F.photo | F.document)
async def handle_file_upload(message: Message):
    """РћР±СЂР°Р±РѕС‚С‡РёРє Р·Р°РіСЂСѓР·РєРё С„Р°Р№Р»РѕРІ (С„РѕС‚Рѕ, РґРѕРєСѓРјРµРЅС‚С‹) РєР°Рє РѕС‚С‡С‘С‚ РїРѕ Р·Р°РґР°С‡Рµ"""
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

        # РќР°С…РѕРґРёРј Р°РєС‚РёРІРЅС‹Рµ Р·Р°РґР°С‡Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (С‡РµСЂРµР· many-to-many СЃРІСЏР·СЊ)
        active_tasks = db.query(Task).join(
            Task.assignees
        ).filter(
            User.id == user.id,
            Task.status == "in_progress"
        ).all()

        if not active_tasks:
            await message.answer(
                "вќЊ РЈ РІР°СЃ РЅРµС‚ Р·Р°РґР°С‡ РІ РїСЂРѕС†РµСЃСЃРµ РІС‹РїРѕР»РЅРµРЅРёСЏ.\n\n"
                "РЎРЅР°С‡Р°Р»Р° РЅР°С‡РЅРёС‚Рµ РІС‹РїРѕР»РЅРµРЅРёРµ Р·Р°РґР°С‡Рё, РЅР°Р¶Р°РІ РєРЅРѕРїРєСѓ 'в–¶пёЏ РќР°С‡Р°С‚СЊ РІС‹РїРѕР»РЅРµРЅРёРµ'."
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
            f"вњ… <b>Р¤Р°Р№Р» РїСЂРёРєСЂРµРїР»С‘РЅ Рє Р·Р°РґР°С‡Рµ!</b>\n\n"
            f"<b>Р—Р°РґР°С‡Р°:</b> {task.title}\n"
            f"<b>Р¤Р°Р№Р»:</b> {file_name}\n"
        )

        if file_size:
            size_mb = file_size / 1024 / 1024
            confirmation += f"<b>Р Р°Р·РјРµСЂ:</b> {size_mb:.2f} РњР‘\n"

        if caption:
            confirmation += f"<b>РћРїРёСЃР°РЅРёРµ:</b> {caption}\n"

        confirmation += f"\nрџ“‹ Р СѓРєРѕРІРѕРґРёС‚РµР»СЊ СЃРјРѕР¶РµС‚ РїСЂРѕСЃРјРѕС‚СЂРµС‚СЊ РѕС‚С‡С‘С‚ РІ РІРµР±-РїР°РЅРµР»Рё"

        await message.answer(confirmation, parse_mode="HTML")

        logger.info(f"File saved: task_id={task.id}, file_type={file_type}, file_id={file_id}")

    except Exception as e:
        logger.error(f"Error handling file upload: {e}", exc_info=True)
        await message.answer("вќЊ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё Р·Р°РіСЂСѓР·РєРµ С„Р°Р№Р»Р°. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ.")
    finally:
        db.close()


@router.message()
async def handle_other_message(message: Message):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РѕСЃС‚Р°Р»СЊРЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№"""
    if message.chat.type == "private":
        await message.answer(
            "РџСЂРёРІРµС‚! рџ‘‹\n\n"
            "РЇ СЂР°Р±РѕС‚Р°СЋ РІ РіСЂСѓРїРїРѕРІС‹С… С‡Р°С‚Р°С…. Р”РѕР±Р°РІСЊС‚Рµ РјРµРЅСЏ РІ РіСЂСѓРїРїСѓ, С‡С‚РѕР±С‹ СЏ РЅР°С‡Р°Р» Р°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ Р·Р°РґР°С‡Рё.\n\n"
            "РСЃРїРѕР»СЊР·СѓР№С‚Рµ /help РґР»СЏ РїРѕР»СѓС‡РµРЅРёСЏ СЃРїСЂР°РІРєРё."
        )



