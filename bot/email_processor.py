# -*- coding: utf-8 -*-
"""
Email Processor
Обработка email писем и создание задач
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from bs4 import BeautifulSoup

from db.database import get_db_session
from db.models import EmailAccount, EmailMessage, Task, PendingTask, User
from bot.ai_extractor import analyze_email_with_ai
from bot.email_handler import fetch_new_emails
from bot.attachment_processor import extract_attachments_from_email, format_attachments_text

logger = logging.getLogger(__name__)


def clean_html_to_text(html_content: str) -> str:
    """
    Конвертирует HTML в чистый текст

    Args:
        html_content: HTML содержимое

    Returns:
        Чистый текст
    """
    if not html_content:
        return ""

    try:
        soup = BeautifulSoup(html_content, 'lxml')
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.decompose()

        # Получаем текст
        text = soup.get_text()

        # Убираем лишние переносы строк
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text
    except Exception as e:
        logger.error(f"Error cleaning HTML: {e}")
        return html_content


def extract_task_from_email(email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Извлекает данные задачи из email используя AI

    Args:
        email_data: Данные email (subject, body_text, body_html, raw_message)

    Returns:
        Словарь с данными задачи или None
    """
    # Формируем текст для анализа
    subject = email_data.get('subject', '')
    body_text = email_data.get('body_text', '')
    body_html = email_data.get('body_html', '')

    # Если нет текста, конвертируем HTML
    if not body_text and body_html:
        body_text = clean_html_to_text(body_html)

    # Обрабатываем вложения если есть
    attachments = []
    attachments_text = ""

    if email_data.get('has_attachments') and email_data.get('raw_message'):
        try:
            raw_message = email_data['raw_message']
            attachments = extract_attachments_from_email(raw_message)

            if attachments:
                attachments_text = format_attachments_text(attachments)
                logger.info(f"Extracted {len(attachments)} attachments with text")
        except Exception as e:
            logger.error(f"Error processing attachments: {e}")

    # Комбинируем тему, тело и вложения
    full_text = f"{subject}\n\n{body_text}{attachments_text}" if body_text else f"{subject}{attachments_text}"

    if not full_text.strip():
        logger.warning("Empty email content, skipping")
        return None

    logger.info(f"Analyzing email: {subject[:50]}...")

    # Используем AI для извлечения задачи (специальный промпт для email)
    try:
        import asyncio
        ai_result = asyncio.run(analyze_email_with_ai(full_text))

        if not ai_result or not ai_result.get("has_task"):
            logger.info("No task found in email")
            return None

        task_data = ai_result.get("task", {})
        task_data['attachments'] = attachments  # Сохраняем информацию о вложениях
        logger.info(f"Task extracted from email: {task_data.get('title', 'No title')}")

        return task_data

    except Exception as e:
        logger.error(f"Error analyzing email with AI: {e}")
        return None


def find_user_by_email(email_address: str) -> Optional[User]:
    """
    Ищет пользователя TaskBridge по email адресу

    Args:
        email_address: Email адрес отправителя

    Returns:
        User или None
    """
    db = get_db_session()

    try:
        # Ищем по email_accounts
        from db.models import EmailAccount
        email_account = db.query(EmailAccount).filter(
            EmailAccount.email_address == email_address
        ).first()

        if email_account:
            return db.query(User).filter(User.id == email_account.user_id).first()

        return None

    finally:
        db.close()


def find_user_by_username(username: str) -> Optional[User]:
    """
    Ищет пользователя по username из задачи

    Args:
        username: Username (без @)

    Returns:
        User или None
    """
    db = get_db_session()

    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        db.close()


def create_task_from_email(
    email_account: EmailAccount,
    email_data: Dict[str, Any],
    task_data: Dict[str, Any],
    email_message: EmailMessage
) -> Optional[int]:
    """
    Создает задачу из email

    Args:
        email_account: Email аккаунт получателя
        email_data: Данные email
        task_data: Данные задачи от AI
        email_message: Сохраненное сообщение в БД

    Returns:
        ID созданной задачи или None
    """
    db = get_db_session()

    try:
        # Получаем владельца email аккаунта
        owner = db.query(User).filter(User.id == email_account.user_id).first()
        if not owner:
            logger.error(f"Email account owner not found: user_id={email_account.user_id}")
            return None

        # Проверяем - является ли отправитель зарегистрированным пользователем
        sender_email = email_data.get('from_address', '')
        sender_user = find_user_by_email(sender_email)

        # Определяем нужно ли автоподтверждение
        needs_confirmation = not email_account.auto_confirm

        # Извлекаем исполнителей
        assignee_usernames = task_data.get("assignee_usernames", [])
        if not assignee_usernames:
            # Fallback на старый формат
            old_assignee = task_data.get("assignee_username")
            if old_assignee:
                assignee_usernames = [old_assignee]

        # Если нет исполнителей - назначаем на владельца email
        if not assignee_usernames:
            assignee_usernames = [owner.username] if owner.username else []

        logger.info(f"Email from: {sender_email}, auto_confirm={email_account.auto_confirm}, needs_confirmation={needs_confirmation}")

        if needs_confirmation:
            # Создаем PendingTask (требует подтверждения)
            pending_task = PendingTask(
                message_id=None,  # У email нет Telegram message_id
                chat_id=owner.telegram_id,  # Отправляем владельцу email аккаунта
                created_by_id=owner.id,
                title=task_data.get("title", email_data.get('subject', 'Задача из email')),
                description=task_data.get("description", email_data.get('body_text', '')),
                assignee_usernames=assignee_usernames if assignee_usernames else None,
                due_date=task_data.get("due_date_parsed"),
                priority=task_data.get("priority", "normal"),
                status="pending"
            )

            db.add(pending_task)
            db.commit()
            db.refresh(pending_task)

            logger.info(f"✅ Created PendingTask #{pending_task.id} from email: {email_data.get('subject', '')}")

            # TODO: Отправить уведомление владельцу о новой задаче требующей подтверждения

            return None  # PendingTask, не Task

        else:
            # Создаем Task автоматически
            task = Task(
                title=task_data.get("title", email_data.get('subject', 'Задача из email')),
                description=task_data.get("description", email_data.get('body_text', '')),
                status="pending",
                priority=task_data.get("priority", "normal"),
                due_date=task_data.get("due_date_parsed"),
                created_by=owner.id
            )

            db.add(task)
            db.flush()  # Получаем ID задачи

            # Назначаем исполнителей
            for username in assignee_usernames:
                assignee = find_user_by_username(username)
                if assignee:
                    task.assignees.append(assignee)
                    logger.info(f"Assigned task to @{username}")

            db.commit()
            db.refresh(task)

            # Связываем email с задачей
            email_message.task_id = task.id
            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            db.commit()

            logger.info(f"✅ Created Task #{task.id} from email: {email_data.get('subject', '')}")

            # TODO: Отправить уведомления исполнителям

            return task.id

    except Exception as e:
        logger.error(f"Error creating task from email: {e}", exc_info=True)
        db.rollback()
        return None

    finally:
        db.close()


def process_email(email_account: EmailAccount, email_data: Dict[str, Any]) -> bool:
    """
    Обрабатывает одно email сообщение

    Args:
        email_account: Email аккаунт
        email_data: Данные письма

    Returns:
        True если успешно обработано
    """
    db = get_db_session()

    try:
        # Проверяем не обработано ли уже это письмо
        message_id = email_data.get('message_id', '')
        existing = db.query(EmailMessage).filter(
            EmailMessage.message_id == message_id
        ).first()

        if existing:
            logger.info(f"Email already processed: {message_id}")
            return False

        # Сохраняем email в БД
        email_message = EmailMessage(
            email_account_id=email_account.id,
            message_id=message_id,
            uid=email_data['uid'],
            subject=email_data.get('subject', ''),
            from_address=email_data.get('from_address', ''),
            to_address=email_data.get('to_address', ''),
            date=email_data.get('date'),
            body_text=email_data.get('body_text', ''),
            body_html=email_data.get('body_html', ''),
            has_attachments=email_data.get('has_attachments', False),
            processed=False
        )

        db.add(email_message)
        db.commit()
        db.refresh(email_message)

        logger.info(f"📧 Processing email: {email_data.get('subject', 'No subject')}")

        # Извлекаем задачу из письма
        task_data = extract_task_from_email(email_data)

        if not task_data:
            logger.info("No task extracted from email")
            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            email_message.error_message = "No task found"
            db.commit()
            return False

        # Создаем задачу
        task_id = create_task_from_email(email_account, email_data, task_data, email_message)

        if task_id:
            logger.info(f"✅ Task #{task_id} created from email")
            return True
        else:
            logger.info("Task requires confirmation or failed to create")
            return True

    except Exception as e:
        logger.error(f"Error processing email: {e}", exc_info=True)
        db.rollback()

        # Сохраняем ошибку
        if email_message:
            email_message.processed = True
            email_message.processed_at = datetime.utcnow()
            email_message.error_message = str(e)
            db.commit()

        return False

    finally:
        db.close()


def check_and_process_emails():
    """
    Проверяет все активные email аккаунты и обрабатывает новые письма
    Вызывается периодически из scheduler
    """
    db = get_db_session()

    try:
        # Получаем все активные email аккаунты
        email_accounts = db.query(EmailAccount).filter(
            EmailAccount.is_active == True
        ).all()

        if not email_accounts:
            logger.info("No active email accounts")
            return

        logger.info(f"📬 Checking {len(email_accounts)} email accounts...")

        for account in email_accounts:
            try:
                logger.info(f"Checking {account.email_address}...")

                # Получаем новые письма
                new_emails = fetch_new_emails(account)

                if not new_emails:
                    continue

                # Обрабатываем каждое письмо
                processed_count = 0
                for email_data in new_emails:
                    if process_email(account, email_data):
                        processed_count += 1

                # Обновляем last_uid
                if new_emails:
                    max_uid = max(email['uid'] for email in new_emails)
                    account.last_uid = max_uid
                    account.last_checked = datetime.utcnow()
                    db.commit()

                logger.info(f"✅ Processed {processed_count}/{len(new_emails)} emails from {account.email_address}")

            except Exception as e:
                logger.error(f"Error checking email account {account.email_address}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in check_and_process_emails: {e}", exc_info=True)

    finally:
        db.close()
