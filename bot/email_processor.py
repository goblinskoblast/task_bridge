# -*- coding: utf-8 -*-
"""Обработка писем и создание задач из почты."""

import asyncio
import logging
from datetime import datetime, timedelta
from html import escape
from typing import Any, Dict, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from bs4 import BeautifulSoup

from bot.ai_extractor import analyze_email_with_ai
from bot.attachment_processor import extract_attachments_from_email, format_attachments_text
from bot.calendar_sync import sync_task_to_connected_calendars
from bot.email_handler import fetch_new_emails
from bot.notifications import get_notification_bot
from config import WEB_APP_DOMAIN
from db.database import get_db_session
from db.models import EmailAccount, EmailAttachment, EmailMessage, Message as MessageModel, PendingTask, Task, User

logger = logging.getLogger(__name__)


def _safe_text(value: str | None) -> str:
    return escape((value or "").strip())


async def _send_email_pending_confirmation(owner: User, pending_task: PendingTask) -> None:
    if not owner.telegram_id or owner.telegram_id == -1:
        logger.warning("Owner %s has no Telegram chat, cannot send email confirmation", owner.id)
        return

    bot = get_notification_bot()
    confirmation_text = (
        "📨 <b>Новая задача из почты требует подтверждения</b>\n\n"
        f"<b>Задача:</b> {_safe_text(pending_task.title)}\n"
    )

    if pending_task.description and pending_task.description != pending_task.title:
        confirmation_text += f"<b>Описание:</b> {_safe_text(pending_task.description)}\n"

    if pending_task.due_date:
        confirmation_text += f"<b>Срок:</b> {pending_task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

    confirmation_text += f"<b>Приоритет:</b> {_safe_text(pending_task.priority)}\n\nПодтвердите создание задачи:"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_task:{pending_task.id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_task:{pending_task.id}"),
            ]
        ]
    )

    sent_message = await bot.send_message(
        chat_id=owner.telegram_id,
        text=confirmation_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    pending_task.telegram_message_id = sent_message.message_id


async def _send_email_task_created_notification(owner: User, task: Task) -> None:
    if not owner.telegram_id or owner.telegram_id == -1:
        logger.warning("Owner %s has no Telegram chat, cannot send created-task notification", owner.id)
        return

    bot = get_notification_bot()
    webapp_url = f"{WEB_APP_DOMAIN}/webapp/index.html?mode=manager&user_id={owner.id}&task_id={task.id}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📱 Открыть задачу", web_app=WebAppInfo(url=webapp_url))]]
    )

    text = (
        "✅ <b>Задача создана из письма</b>\n\n"
        f"<b>Задача:</b> {_safe_text(task.title)}\n"
    )
    if task.description and task.description != task.title:
        text += f"<b>Описание:</b> {_safe_text(task.description)}\n"
    if task.due_date:
        text += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"
    text += f"<b>Приоритет:</b> {_safe_text(task.priority)}"

    await bot.send_message(
        chat_id=owner.telegram_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


def clean_html_to_text(html_content: str) -> str:
    if not html_content:
        return ""

    try:
        soup = BeautifulSoup(html_content, "lxml")
        for script in soup(["script", "style"]):
            script.decompose()

        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        return "\n".join(chunk for chunk in chunks if chunk)
    except Exception as exc:
        logger.error("Error cleaning HTML: %s", exc)
        return html_content


def extract_task_from_email(email_data: Dict[str, Any], attachments: Optional[list] = None) -> Optional[Dict[str, Any]]:
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")
    body_html = email_data.get("body_html", "")

    if not body_text and body_html:
        body_text = clean_html_to_text(body_html)

    attachments = attachments or []
    attachments_text = ""

    if not attachments and email_data.get("has_attachments") and email_data.get("raw_message"):
        try:
            attachments = extract_attachments_from_email(email_data["raw_message"])
        except Exception as exc:
            logger.error("Error processing attachments: %s", exc, exc_info=True)
            attachments = []

    if attachments:
        attachments_text = format_attachments_text(attachments)

    if not (subject.strip() or body_text.strip() or attachments_text.strip()):
        logger.warning("Empty email content, skipping")
        return None

    logger.info("Analyzing email: %s...", subject[:50])

    try:
        ai_result = asyncio.run(
            analyze_email_with_ai(
                subject=subject,
                body_text=body_text,
                from_address=email_data.get("from_address", ""),
                attachments_text=attachments_text,
            )
        )

        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in email")
            return None

        task_data = ai_result.get("task", {})
        task_data["attachments"] = attachments
        logger.info("Task extracted from email: %s", task_data.get("title", "Без названия"))
        return task_data
    except Exception as exc:
        logger.error("Error analyzing email with AI: %s", exc, exc_info=True)
        return None


def find_user_by_email(email_address: str) -> Optional[User]:
    db = get_db_session()
    try:
        from db.models import EmailAccount as EmailAccountModel

        email_account = db.query(EmailAccountModel).filter(EmailAccountModel.email_address == email_address).first()
        if email_account:
            return db.query(User).filter(User.id == email_account.user_id).first()
        return None
    finally:
        db.close()


def find_user_by_username(username: str, db=None) -> Optional[User]:
    own_session = db is None
    if own_session:
        db = get_db_session()

    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        if own_session:
            db.close()


def create_task_from_email(
    email_account: EmailAccount,
    email_data: Dict[str, Any],
    task_data: Dict[str, Any],
    email_message: EmailMessage,
) -> Optional[int]:
    db = get_db_session()
    try:
        owner = db.query(User).filter(User.id == email_account.user_id).first()
        if not owner:
            logger.error("Email account owner not found: user_id=%s", email_account.user_id)
            return None

        sender_email = email_data.get("from_address", "")
        needs_confirmation = not email_account.auto_confirm
        task_due_date = task_data.get("due_date_parsed") or (datetime.now() + timedelta(hours=24))

        assignee_usernames = task_data.get("assignee_usernames", []) or []
        if not assignee_usernames and task_data.get("assignee_username"):
            assignee_usernames = [task_data["assignee_username"]]
        if not assignee_usernames and owner.username:
            assignee_usernames = [owner.username]

        logger.info(
            "Email from: %s, auto_confirm=%s, needs_confirmation=%s",
            sender_email,
            email_account.auto_confirm,
            needs_confirmation,
        )

        if needs_confirmation:
            synthetic_message = MessageModel(
                message_id=email_message.uid,
                chat_id=owner.telegram_id or owner.id,
                user_id=owner.id,
                text=task_data.get("description")
                or email_data.get("body_text", "")
                or task_data.get("title", "Задача из email"),
                date=email_data.get("date") or datetime.utcnow(),
                has_task=True,
            )
            db.add(synthetic_message)
            db.flush()

            pending_task = PendingTask(
                message_id=synthetic_message.id,
                chat_id=owner.telegram_id or owner.id,
                created_by_id=owner.id,
                title=task_data.get("title") or email_data.get("subject", "Задача из email"),
                description=task_data.get("description") or email_data.get("body_text", ""),
                assignee_usernames=assignee_usernames or None,
                assignee_username=assignee_usernames[0] if assignee_usernames else None,
                due_date=task_due_date,
                priority=task_data.get("priority", "normal"),
                status="pending",
            )
            db.add(pending_task)
            db.commit()
            db.refresh(pending_task)

            asyncio.run(_send_email_pending_confirmation(owner, pending_task))

            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            email_message.error_message = "Awaiting owner confirmation"
            db.commit()

            logger.info("Created PendingTask #%s from email: %s", pending_task.id, email_data.get("subject", ""))
            return None

        task = Task(
            title=task_data.get("title") or email_data.get("subject", "Задача из email"),
            description=task_data.get("description") or email_data.get("body_text", ""),
            status="pending",
            priority=task_data.get("priority", "normal"),
            due_date=task_due_date,
            created_by=owner.id,
        )

        db.add(task)
        db.flush()

        for username in assignee_usernames:
            assignee = find_user_by_username(username, db=db)
            if assignee:
                task.assignees.append(assignee)
                logger.info("Assigned task to @%s", username)

        db.commit()
        db.refresh(task)
        sync_task_to_connected_calendars(task, db)

        email_message.task_id = task.id
        email_message.processed = True
        email_message.processed_at = datetime.utcnow()
        email_message.error_message = None
        db.commit()

        asyncio.run(_send_email_task_created_notification(owner, task))

        logger.info("Created Task #%s from email: %s", task.id, email_data.get("subject", ""))
        return task.id
    except Exception as exc:
        logger.error("Error creating task from email: %s", exc, exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()


def process_email(email_account: EmailAccount, email_data: Dict[str, Any]) -> bool:
    db = get_db_session()
    email_message = None

    try:
        message_id = email_data.get("message_id", "")
        existing = db.query(EmailMessage).filter(EmailMessage.message_id == message_id).first()
        if existing:
            logger.info("Email already processed: %s", message_id)
            return False

        extracted_attachments = []
        if email_data.get("has_attachments") and email_data.get("raw_message"):
            try:
                extracted_attachments = extract_attachments_from_email(email_data["raw_message"])
            except Exception as attachment_error:
                logger.error(
                    "Attachment extraction failed, continuing with email body only: %s",
                    attachment_error,
                    exc_info=True,
                )
                extracted_attachments = []

        email_message = EmailMessage(
            email_account_id=email_account.id,
            message_id=message_id,
            uid=email_data["uid"],
            subject=email_data.get("subject", ""),
            from_address=email_data.get("from_address", ""),
            to_address=email_data.get("to_address", ""),
            date=email_data.get("date"),
            body_text=email_data.get("body_text", ""),
            body_html=email_data.get("body_html", ""),
            has_attachments=email_data.get("has_attachments", False),
            processed=False,
        )

        db.add(email_message)
        db.commit()
        db.refresh(email_message)

        for attachment in extracted_attachments:
            db.add(
                EmailAttachment(
                    email_message_id=email_message.id,
                    filename=attachment.get("filename", "attachment"),
                    content_type=attachment.get("content_type"),
                    file_size=attachment.get("size"),
                    extracted_text=attachment.get("text"),
                    file_data=attachment.get("file_data", b""),
                )
            )
        db.commit()

        logger.info("Processing email: %s", email_data.get("subject", "Без темы"))

        task_data = extract_task_from_email(email_data, attachments=extracted_attachments)
        if not task_data:
            logger.info("No task extracted from email")
            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            email_message.error_message = "No task found"
            db.commit()
            return False

        task_id = create_task_from_email(email_account, email_data, task_data, email_message)

        email_message.processed = True
        email_message.processed_at = datetime.utcnow()
        if task_id:
            email_message.task_id = task_id
            email_message.error_message = None
        elif email_message.error_message is None:
            email_message.error_message = "Pending confirmation or task creation failed"
        db.commit()

        if task_id:
            logger.info("Task #%s created from email", task_id)
        else:
            logger.info("Task requires confirmation or was not created automatically")
        return True
    except Exception as exc:
        logger.error("Error processing email: %s", exc, exc_info=True)
        db.rollback()
        if email_message:
            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            email_message.error_message = str(exc)
            db.commit()
        return False
    finally:
        db.close()


def check_and_process_emails() -> None:
    db = get_db_session()
    try:
        email_accounts = db.query(EmailAccount).filter(EmailAccount.is_active == True).all()
        if not email_accounts:
            logger.info("No active email accounts")
            return

        logger.info("Checking %s email accounts...", len(email_accounts))
        for account in email_accounts:
            try:
                logger.info("Checking %s...", account.email_address)
                new_emails = fetch_new_emails(account)
                if not new_emails:
                    continue

                processed_count = 0
                for email_data in new_emails:
                    if process_email(account, email_data):
                        processed_count += 1

                if new_emails:
                    account.last_uid = max(email["uid"] for email in new_emails)
                    account.last_checked = datetime.utcnow()
                    db.commit()

                logger.info(
                    "Processed %s/%s emails from %s",
                    processed_count,
                    len(new_emails),
                    account.email_address,
                )
            except Exception as exc:
                logger.error("Error checking email account %s: %s", account.email_address, exc, exc_info=True)
                continue
    except Exception as exc:
        logger.error("Error in check_and_process_emails: %s", exc, exc_info=True)
    finally:
        db.close()
