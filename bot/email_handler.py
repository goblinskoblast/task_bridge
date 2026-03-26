# -*- coding: utf-8 -*-
"""
Email IMAP Integration Handler
Р¤СѓРЅРєС†РёРё РґР»СЏ СЂР°Р±РѕС‚С‹ СЃ IMAP СЃРµСЂРІРµСЂР°РјРё Рё РїРѕР»СѓС‡РµРЅРёСЏ РїРёСЃРµРј
"""

import logging
import email
from email.header import decode_header
from imapclient import IMAPClient
from datetime import datetime
from typing import Optional, List, Dict, Any
import re
import json
from urllib import parse as urlparse
from urllib import request as urlrequest

from db.database import get_db_session
from db.models import EmailAccount, EmailMessage
from config import GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, YANDEX_OAUTH_CLIENT_ID, YANDEX_OAUTH_CLIENT_SECRET

logger = logging.getLogger(__name__)


# РџРѕРїСѓР»СЏСЂРЅС‹Рµ IMAP СЃРµСЂРІРµСЂС‹
IMAP_SERVERS = {
    "gmail.com": {"server": "imap.gmail.com", "port": 993},
    "outlook.com": {"server": "outlook.office365.com", "port": 993},
    "hotmail.com": {"server": "outlook.office365.com", "port": 993},
    "yandex.ru": {"server": "imap.yandex.com", "port": 993},
    "yandex.com": {"server": "imap.yandex.com", "port": 993},
    "mail.ru": {"server": "imap.mail.ru", "port": 993},
    "yahoo.com": {"server": "imap.mail.yahoo.com", "port": 993},
}

GOOGLE_REFRESH_PREFIX = "oauth_refresh:"
YANDEX_REFRESH_PREFIX = "yandex_oauth_refresh:"
PRIMARY_INBOX_FOLDERS = {"INBOX", "Inbox", "inbox"}
NON_PRIMARY_FOLDERS = {
    "spam",
    "junk",
    "trash",
    "bin",
    "deleted",
    "archive",
    "all mail",
    "[gmail]/spam",
    "[gmail]/junk",
    "[gmail]/all mail",
}


def _resolve_primary_folder(folder_name: Optional[str]) -> str:
    raw = (folder_name or "").strip()
    if not raw:
        return "INBOX"

    lowered = raw.lower()
    if raw in PRIMARY_INBOX_FOLDERS:
        return "INBOX"

    if lowered in NON_PRIMARY_FOLDERS:
        logger.warning("Non-primary email folder '%s' requested; forcing INBOX", raw)
        return "INBOX"

    if "spam" in lowered or "junk" in lowered:
        logger.warning("Spam/junk-like folder '%s' requested; forcing INBOX", raw)
        return "INBOX"

    return "INBOX"


def _get_google_access_token(refresh_token: str) -> Optional[str]:
    """Exchange Google refresh token to short-lived access token."""
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
        logger.error("Google OAuth credentials are not configured")
        return None

    try:
        payload = urlparse.urlencode({
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode("utf-8")

        req = urlrequest.Request(
            "https://oauth2.googleapis.com/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urlrequest.urlopen(req, timeout=20) as response:
            token_payload = json.loads(response.read().decode("utf-8"))

        access_token = token_payload.get("access_token")
        if not access_token:
            logger.error(f"Google token response missing access_token: {token_payload}")
            return None

        return access_token
    except Exception as e:
        logger.error(f"Failed to refresh Google access token: {e}")
        return None


def _get_yandex_access_token(refresh_token: str) -> Optional[str]:
    if not YANDEX_OAUTH_CLIENT_ID or not YANDEX_OAUTH_CLIENT_SECRET:
        logger.error("Yandex OAuth credentials are not configured")
        return None

    try:
        payload = urlparse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": YANDEX_OAUTH_CLIENT_ID,
            "client_secret": YANDEX_OAUTH_CLIENT_SECRET,
        }).encode("utf-8")

        req = urlrequest.Request(
            "https://oauth.yandex.ru/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urlrequest.urlopen(req, timeout=20) as response:
            token_payload = json.loads(response.read().decode("utf-8"))

        access_token = token_payload.get("access_token")
        if not access_token:
            logger.error(f"Yandex token response missing access_token: {token_payload}")
            return None

        return access_token
    except Exception as e:
        logger.error(f"Failed to refresh Yandex access token: {e}")
        return None


def get_imap_server(email_address: str) -> Dict[str, Any]:
    """
    РђРІС‚РѕРѕРїСЂРµРґРµР»РµРЅРёРµ IMAP СЃРµСЂРІРµСЂР° РїРѕ email Р°РґСЂРµСЃСѓ

    Args:
        email_address: Email Р°РґСЂРµСЃ (example@gmail.com)

    Returns:
        Dict СЃ РєР»СЋС‡Р°РјРё server Рё port
    """
    domain = email_address.split("@")[-1].lower()

    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]

    # Р”Р»СЏ РЅРµРёР·РІРµСЃС‚РЅС‹С… РґРѕРјРµРЅРѕРІ - СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№ IMAP
    return {"server": f"imap.{domain}", "port": 993}


def test_imap_connection(
    server: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool = True
) -> tuple[bool, Optional[str]]:
    """
    РўРµСЃС‚РёСЂСѓРµС‚ IMAP РїРѕРґРєР»СЋС‡РµРЅРёРµ

    Args:
        server: IMAP СЃРµСЂРІРµСЂ (imap.gmail.com)
        port: IMAP РїРѕСЂС‚ (993)
        username: РРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (РѕР±С‹С‡РЅРѕ email)
        password: РџР°СЂРѕР»СЊ РёР»Рё App Password
        use_ssl: РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ SSL

    Returns:
        (success: bool, error_message: Optional[str])
    """
    try:
        client = IMAPClient(server, port=port, ssl=use_ssl)
        client.login(username, password)
        client.select_folder("INBOX")
        client.logout()

        logger.info(f"вњ… IMAP connection test successful: {username}@{server}")
        return True, None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"вќЊ IMAP connection test failed: {username}@{server} - {error_msg}")
        return False, error_msg


def connect_imap(email_account: EmailAccount) -> Optional[IMAPClient]:
    """
    РџРѕРґРєР»СЋС‡Р°РµС‚СЃСЏ Рє IMAP СЃРµСЂРІРµСЂСѓ

    Args:
        email_account: РњРѕРґРµР»СЊ EmailAccount РёР· Р‘Р”

    Returns:
        IMAPClient РёР»Рё None РІ СЃР»СѓС‡Р°Рµ РѕС€РёР±РєРё
    """
    try:
        client = IMAPClient(
            email_account.imap_server,
            port=email_account.imap_port,
            ssl=email_account.use_ssl
        )

        raw_secret = email_account.imap_password or ""
        if raw_secret.startswith(GOOGLE_REFRESH_PREFIX):
            refresh_token = raw_secret[len(GOOGLE_REFRESH_PREFIX):]
            access_token = _get_google_access_token(refresh_token)
            if not access_token:
                logger.error(f"Failed to get Google access token for {email_account.email_address}")
                return None
            client.oauth2_login(email_account.imap_username, access_token)
        elif raw_secret.startswith(YANDEX_REFRESH_PREFIX):
            refresh_token = raw_secret[len(YANDEX_REFRESH_PREFIX):]
            access_token = _get_yandex_access_token(refresh_token)
            if not access_token:
                logger.error(f"Failed to get Yandex access token for {email_account.email_address}")
                return None
            client.oauth2_login(email_account.imap_username, access_token)
        else:
            client.login(email_account.imap_username, raw_secret)
        client.select_folder(_resolve_primary_folder(email_account.folder))

        logger.info(f"вњ… Connected to IMAP: {email_account.email_address}")
        return client

    except Exception as e:
        logger.error(f"вќЊ Failed to connect to IMAP: {email_account.email_address} - {e}")
        return None


def decode_mime_header(header_value: str) -> str:
    """
    Р”РµРєРѕРґРёСЂСѓРµС‚ MIME Р·Р°РіРѕР»РѕРІРѕРє email

    Args:
        header_value: Р—РЅР°С‡РµРЅРёРµ Р·Р°РіРѕР»РѕРІРєР°

    Returns:
        Р”РµРєРѕРґРёСЂРѕРІР°РЅРЅР°СЏ СЃС‚СЂРѕРєР°
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
    РР·РІР»РµРєР°РµС‚ С‚РµРєСЃС‚ Рё HTML РёР· email СЃРѕРѕР±С‰РµРЅРёСЏ

    Args:
        msg: Email message РѕР±СЉРµРєС‚

    Returns:
        (text_body, html_body)
    """
    text_body = None
    html_body = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # РџСЂРѕРїСѓСЃРєР°РµРј РІР»РѕР¶РµРЅРёСЏ
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
        # РџСЂРѕСЃС‚РѕРµ СЃРѕРѕР±С‰РµРЅРёРµ
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
    РџСЂРѕРІРµСЂСЏРµС‚ СЃРѕРѕС‚РІРµС‚СЃС‚РІРёРµ РїРёСЃСЊРјР° С„РёР»СЊС‚СЂР°Рј

    Args:
        email_account: Email Р°РєРєР°СѓРЅС‚ СЃ РЅР°СЃС‚СЂРѕР№РєР°РјРё С„РёР»СЊС‚СЂРѕРІ
        from_address: Email РѕС‚РїСЂР°РІРёС‚РµР»СЏ
        subject: РўРµРјР° РїРёСЃСЊРјР°

    Returns:
        True РµСЃР»Рё РїРёСЃСЊРјРѕ РїСЂРѕС…РѕРґРёС‚ С„РёР»СЊС‚СЂС‹
    """
    # Р¤РёР»СЊС‚СЂ РїРѕ РѕС‚РїСЂР°РІРёС‚РµР»СЋ
    if email_account.only_from_addresses:
        allowed = email_account.only_from_addresses
        if not any(addr.lower() in from_address.lower() for addr in allowed):
            logger.info(f"вќЊ Message from {from_address} filtered out (not in allowed list)")
            return False

    # Р¤РёР»СЊС‚СЂ РїРѕ РєР»СЋС‡РµРІС‹Рј СЃР»РѕРІР°Рј РІ С‚РµРјРµ
    if email_account.subject_keywords:
        keywords = email_account.subject_keywords
        subject_lower = subject.lower()

        if not any(keyword.lower() in subject_lower for keyword in keywords):
            logger.info(f"вќЊ Message with subject '{subject}' filtered out (no keywords match)")
            return False

    return True


def fetch_new_emails(email_account: EmailAccount) -> List[Dict[str, Any]]:
    """
    РџРѕР»СѓС‡Р°РµС‚ РЅРѕРІС‹Рµ РїРёСЃСЊРјР° РёР· IMAP

    Args:
        email_account: Email Р°РєРєР°СѓРЅС‚ РґР»СЏ РїСЂРѕРІРµСЂРєРё

    Returns:
        РЎРїРёСЃРѕРє СЃР»РѕРІР°СЂРµР№ СЃ РґР°РЅРЅС‹РјРё РїРёСЃРµРј
    """
    client = connect_imap(email_account)
    if not client:
        return []

    try:
        all_messages = client.search(['ALL'])

        if email_account.last_uid == 0 and email_account.last_checked is None:
            unseen_messages = client.search(['UNSEEN'])
            if unseen_messages:
                new_messages = unseen_messages
                logger.info(f"First check for {email_account.email_address}: processing {len(new_messages)} unseen emails")
            else:
                if all_messages:
                    max_uid = max(all_messages)
                    logger.info(f"First check for {email_account.email_address}: setting last_uid to {max_uid} (skipping {len(all_messages)} old emails)")

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
                return []
        else:
            new_messages = [uid for uid in all_messages if uid > email_account.last_uid]

        if not new_messages:
            logger.info(f"📭 No new emails for {email_account.email_address}")
            client.logout()
            return []

        logger.info(f"📬 Found {len(new_messages)} new emails for {email_account.email_address}")
        response = client.fetch(new_messages, ['RFC822', 'FLAGS'])

        emails_data = []
        for uid, data in response.items():
            try:
                raw_email = data[b'RFC822']
                msg = email.message_from_bytes(raw_email)

                subject = decode_mime_header(msg.get('Subject', ''))
                from_header = msg.get('From', '')
                to_header = msg.get('To', '')
                message_id = msg.get('Message-ID', '')
                date_header = msg.get('Date', '')

                from_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
                from_address = from_match.group(0) if from_match else from_header

                if not check_message_filters(email_account, from_address, subject):
                    continue

                text_body, html_body = extract_email_body(msg)

                has_attachments = False
                for part in msg.walk():
                    if part.get_content_disposition() == 'attachment':
                        has_attachments = True
                        break

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
                    'raw_message': msg,
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


def initialize_email_account_sync_state(email_account: EmailAccount) -> None:
    """
    Initialize the sync cursor for a newly connected account so historical emails
    are skipped and only emails arriving after connection are processed.
    """
    client = connect_imap(email_account)
    if not client:
        logger.warning(f"Could not initialize sync state for {email_account.email_address}")
        return

    try:
        all_messages = client.search(['ALL'])
        email_account.last_uid = max(all_messages) if all_messages else 0
        email_account.last_checked = datetime.utcnow()
        logger.info(
            f"Initialized sync state for {email_account.email_address}: "
            f"last_uid={email_account.last_uid}"
        )
    except Exception as e:
        logger.error(f"Failed to initialize sync state for {email_account.email_address}: {e}")
    finally:
        try:
            client.logout()
        except Exception:
            pass
