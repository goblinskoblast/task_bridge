# -*- coding: utf-8 -*-
"""
Email IMAP Integration Handler
Функции для работы с IMAP серверами и получения писем
"""

import logging
import email
from email.header import decode_header
from imapclient import IMAPClient
from datetime import datetime
from typing import Optional, List, Dict, Any
import re

from db.database import get_db_session
from db.models import EmailAccount, EmailMessage

logger = logging.getLogger(__name__)


# Популярные IMAP серверы
IMAP_SERVERS = {
    "gmail.com": {"server": "imap.gmail.com", "port": 993},
    "outlook.com": {"server": "outlook.office365.com", "port": 993},
    "hotmail.com": {"server": "outlook.office365.com", "port": 993},
    "yandex.ru": {"server": "imap.yandex.ru", "port": 993},
    "yandex.com": {"server": "imap.yandex.com", "port": 993},
    "mail.ru": {"server": "imap.mail.ru", "port": 993},
    "yahoo.com": {"server": "imap.mail.yahoo.com", "port": 993},
}


def get_imap_server(email_address: str) -> Dict[str, Any]:
    """
    Автоопределение IMAP сервера по email адресу

    Args:
        email_address: Email адрес (example@gmail.com)

    Returns:
        Dict с ключами server и port
    """
    domain = email_address.split("@")[-1].lower()

    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]

    # Для неизвестных доменов - стандартный IMAP
    return {"server": f"imap.{domain}", "port": 993}


def test_imap_connection(
    server: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool = True
) -> tuple[bool, Optional[str]]:
    """
    Тестирует IMAP подключение

    Args:
        server: IMAP сервер (imap.gmail.com)
        port: IMAP порт (993)
        username: Имя пользователя (обычно email)
        password: Пароль или App Password
        use_ssl: Использовать SSL

    Returns:
        (success: bool, error_message: Optional[str])
    """
    try:
        client = IMAPClient(server, port=port, ssl=use_ssl)
        client.login(username, password)
        client.select_folder("INBOX")
        client.logout()

        logger.info(f"✅ IMAP connection test successful: {username}@{server}")
        return True, None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ IMAP connection test failed: {username}@{server} - {error_msg}")
        return False, error_msg


def connect_imap(email_account: EmailAccount) -> Optional[IMAPClient]:
    """
    Подключается к IMAP серверу

    Args:
        email_account: Модель EmailAccount из БД

    Returns:
        IMAPClient или None в случае ошибки
    """
    try:
        client = IMAPClient(
            email_account.imap_server,
            port=email_account.imap_port,
            ssl=email_account.use_ssl
        )

        client.login(email_account.imap_username, email_account.imap_password)
        client.select_folder(email_account.folder)

        logger.info(f"✅ Connected to IMAP: {email_account.email_address}")
        return client

    except Exception as e:
        logger.error(f"❌ Failed to connect to IMAP: {email_account.email_address} - {e}")
        return None


def decode_mime_header(header_value: str) -> str:
    """
    Декодирует MIME заголовок email

    Args:
        header_value: Значение заголовка

    Returns:
        Декодированная строка
    """
    if not header_value:
        return ""

    decoded_parts = decode_header(header_value)
    result = []

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding:
                try:
                    result.append(part.decode(encoding))
                except:
                    result.append(part.decode('utf-8', errors='ignore'))
            else:
                result.append(part.decode('utf-8', errors='ignore'))
        else:
            result.append(str(part))

    return "".join(result)


def extract_email_body(msg: email.message.Message) -> tuple[Optional[str], Optional[str]]:
    """
    Извлекает текст и HTML из email сообщения

    Args:
        msg: Email message объект

    Returns:
        (text_body, html_body)
    """
    text_body = None
    html_body = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # Пропускаем вложения
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain" and text_body is None:
                try:
                    text_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass

            elif content_type == "text/html" and html_body is None:
                try:
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass
    else:
        # Простое сообщение
        content_type = msg.get_content_type()

        if content_type == "text/plain":
            try:
                text_body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                pass
        elif content_type == "text/html":
            try:
                html_body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                pass

    return text_body, html_body


def check_message_filters(
    email_account: EmailAccount,
    from_address: str,
    subject: str
) -> bool:
    """
    Проверяет соответствие письма фильтрам

    Args:
        email_account: Email аккаунт с настройками фильтров
        from_address: Email отправителя
        subject: Тема письма

    Returns:
        True если письмо проходит фильтры
    """
    # Фильтр по отправителю
    if email_account.only_from_addresses:
        allowed = email_account.only_from_addresses
        if not any(addr.lower() in from_address.lower() for addr in allowed):
            logger.info(f"❌ Message from {from_address} filtered out (not in allowed list)")
            return False

    # Фильтр по ключевым словам в теме
    if email_account.subject_keywords:
        keywords = email_account.subject_keywords
        subject_lower = subject.lower()

        if not any(keyword.lower() in subject_lower for keyword in keywords):
            logger.info(f"❌ Message with subject '{subject}' filtered out (no keywords match)")
            return False

    return True


def fetch_new_emails(email_account: EmailAccount) -> List[Dict[str, Any]]:
    """
    Получает новые письма из IMAP

    Args:
        email_account: Email аккаунт для проверки

    Returns:
        Список словарей с данными писем
    """
    client = connect_imap(email_account)
    if not client:
        return []

    try:
        # Получаем все UID в папке
        messages = client.search(['ALL'])

        # ПЕРВАЯ ПРОВЕРКА: Инициализация last_uid без обработки старых писем
        if email_account.last_uid == 0 and email_account.last_checked is None:
            if messages:
                max_uid = max(messages)
                logger.info(f"🆕 First check for {email_account.email_address}: setting last_uid to {max_uid} (skipping {len(messages)} old emails)")

                # Обновляем last_uid в БД чтобы начать проверку с этого момента
                from db.database import get_db_session
                db = get_db_session()
                try:
                    email_account.last_uid = max_uid
                    email_account.last_checked = datetime.utcnow()
                    db.merge(email_account)
                    db.commit()
                except Exception as e:
                    logger.error(f"Failed to update last_uid: {e}")
                    db.rollback()
                finally:
                    db.close()

            client.logout()
            return []  # Не обрабатываем старые письма

        # Фильтруем только новые (UID > last_uid)
        new_messages = [uid for uid in messages if uid > email_account.last_uid]

        if not new_messages:
            logger.info(f"📭 No new emails for {email_account.email_address}")
            client.logout()
            return []

        logger.info(f"📬 Found {len(new_messages)} new emails for {email_account.email_address}")

        # Получаем данные писем
        response = client.fetch(new_messages, ['RFC822', 'FLAGS'])

        emails_data = []

        for uid, data in response.items():
            try:
                raw_email = data[b'RFC822']
                msg = email.message_from_bytes(raw_email)

                # Извлекаем заголовки
                subject = decode_mime_header(msg.get('Subject', ''))
                from_header = msg.get('From', '')
                to_header = msg.get('To', '')
                message_id = msg.get('Message-ID', '')
                date_header = msg.get('Date', '')

                # Парсим email адрес отправителя
                from_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
                from_address = from_match.group(0) if from_match else from_header

                # Проверяем фильтры
                if not check_message_filters(email_account, from_address, subject):
                    continue

                # Извлекаем тело письма
                text_body, html_body = extract_email_body(msg)

                # Проверяем вложения
                has_attachments = False
                for part in msg.walk():
                    if part.get_content_disposition() == 'attachment':
                        has_attachments = True
                        break

                # Парсим дату
                email_date = None
                if date_header:
                    try:
                        from email.utils import parsedate_to_datetime
                        email_date = parsedate_to_datetime(date_header)
                    except:
                        pass

                emails_data.append({
                    'uid': uid,
                    'message_id': message_id,
                    'subject': subject,
                    'from_address': from_address,
                    'to_address': to_header,
                    'date': email_date,
                    'body_text': text_body,
                    'body_html': html_body,
                    'has_attachments': has_attachments,
                    'raw_message': msg,  # Полное сообщение для обработки вложений
                })

            except Exception as e:
                logger.error(f"Error processing email UID {uid}: {e}")
                continue

        client.logout()

        logger.info(f"✅ Processed {len(emails_data)} emails (passed filters)")
        return emails_data

    except Exception as e:
        logger.error(f"Error fetching emails: {e}")
        if client:
            try:
                client.logout()
            except:
                pass
        return []
