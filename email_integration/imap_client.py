"""
IMAP клиент для чтения писем из email аккаунтов
"""
import logging
import email
from email.header import decode_header
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import imaplib
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class IMAPClient:
    """Клиент для работы с IMAP серверами"""

    def __init__(self, server: str, port: int, username: str, password: str, use_ssl: bool = True):
        """
        Инициализация IMAP клиента

        Args:
            server: IMAP сервер (например, imap.gmail.com)
            port: Порт (обычно 993 для SSL)
            username: Имя пользователя
            password: Пароль
            use_ssl: Использовать SSL соединение
        """
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.connection: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        """
        Подключение к IMAP серверу

        Returns:
            True если подключение успешно, False иначе
        """
        try:
            if self.use_ssl:
                self.connection = imaplib.IMAP4_SSL(self.server, self.port)
            else:
                self.connection = imaplib.IMAP4(self.server, self.port)

            self.connection.login(self.username, self.password)
            logger.info(f"Successfully connected to {self.server}")
            return True

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP authentication error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            return False

    def disconnect(self):
        """Отключение от сервера"""
        if self.connection:
            try:
                self.connection.logout()
                logger.info(f"Disconnected from {self.server}")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.connection = None

    def select_folder(self, folder: str = "INBOX") -> bool:
        """
        Выбрать папку для чтения

        Args:
            folder: Название папки (по умолчанию INBOX)

        Returns:
            True если папка выбрана успешно
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return False

        try:
            status, messages = self.connection.select(folder)
            if status == "OK":
                logger.info(f"Selected folder: {folder}")
                return True
            else:
                logger.error(f"Failed to select folder {folder}: {status}")
                return False
        except Exception as e:
            logger.error(f"Error selecting folder: {e}")
            return False

    def get_new_message_uids(self, last_uid: int = 0) -> List[int]:
        """
        Получить UIDs новых непрочитанных сообщений

        Args:
            last_uid: Последний обработанный UID

        Returns:
            Список UIDs новых сообщений
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return []

        try:
            # Поиск всех сообщений
            status, data = self.connection.uid('search', None, 'ALL')

            if status != "OK":
                logger.error(f"Failed to search messages: {status}")
                return []

            # Парсинг UIDs
            uid_list = data[0].split()
            uids = [int(uid) for uid in uid_list]

            # Фильтрация новых сообщений
            new_uids = [uid for uid in uids if uid > last_uid]

            logger.info(f"Found {len(new_uids)} new messages (last_uid={last_uid})")
            return sorted(new_uids)

        except Exception as e:
            logger.error(f"Error getting message UIDs: {e}")
            return []

    def fetch_message(self, uid: int) -> Optional[Dict]:
        """
        Получить сообщение по UID

        Args:
            uid: UID сообщения

        Returns:
            Словарь с данными сообщения или None
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return None

        try:
            status, data = self.connection.uid('fetch', str(uid), '(RFC822)')

            if status != "OK":
                logger.error(f"Failed to fetch message UID {uid}")
                return None

            raw_email = data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # Парсинг email
            message_data = {
                'uid': uid,
                'message_id': email_message.get('Message-ID', ''),
                'subject': self._decode_header(email_message.get('Subject', '')),
                'from': email_message.get('From', ''),
                'to': email_message.get('To', ''),
                'date': self._parse_date(email_message.get('Date', '')),
                'body_text': '',
                'body_html': '',
                'has_attachments': False,
                'attachments': []
            }

            # Извлечение тела письма
            if email_message.is_multipart():
                for part in email_message.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    # Текстовое содержимое
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        try:
                            message_data['body_text'] = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except Exception as e:
                            logger.error(f"Error decoding text part: {e}")

                    elif content_type == "text/html" and "attachment" not in content_disposition:
                        try:
                            message_data['body_html'] = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except Exception as e:
                            logger.error(f"Error decoding HTML part: {e}")

                    # Вложения
                    elif "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            message_data['has_attachments'] = True
                            message_data['attachments'].append({
                                'filename': self._decode_header(filename),
                                'content_type': content_type,
                                'size': len(part.get_payload(decode=True) or b'')
                            })
            else:
                # Простое сообщение без multipart
                try:
                    content_type = email_message.get_content_type()
                    body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

                    if content_type == "text/html":
                        message_data['body_html'] = body
                    else:
                        message_data['body_text'] = body
                except Exception as e:
                    logger.error(f"Error decoding message body: {e}")

            # Если есть HTML но нет текста, конвертируем HTML в текст
            if message_data['body_html'] and not message_data['body_text']:
                message_data['body_text'] = self._html_to_text(message_data['body_html'])

            return message_data

        except Exception as e:
            logger.error(f"Error fetching message UID {uid}: {e}")
            return None

    @staticmethod
    def _decode_header(header_value: str) -> str:
        """Декодирование заголовка email"""
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or 'utf-8', errors='ignore'))
                except Exception:
                    decoded_parts.append(part.decode('utf-8', errors='ignore'))
            else:
                decoded_parts.append(str(part))

        return ' '.join(decoded_parts)

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Парсинг даты из email заголовка"""
        if not date_str:
            return None

        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}")
            return None

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Конвертация HTML в текст"""
        try:
            soup = BeautifulSoup(html, 'lxml')

            # Удаление скриптов и стилей
            for script in soup(["script", "style"]):
                script.decompose()

            # Извлечение текста
            text = soup.get_text()

            # Очистка множественных пробелов и переносов
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)

            return text
        except Exception as e:
            logger.error(f"Error converting HTML to text: {e}")
            return html

    def test_connection(self) -> Tuple[bool, str]:
        """
        Тестирование подключения к IMAP серверу

        Returns:
            Кортеж (успех, сообщение)
        """
        try:
            if self.connect():
                if self.select_folder("INBOX"):
                    message_count = len(self.get_new_message_uids())
                    self.disconnect()
                    return True, f"Connection successful. Found {message_count} messages in INBOX."
                else:
                    self.disconnect()
                    return False, "Connected but failed to select INBOX folder"
            else:
                return False, "Failed to connect to IMAP server. Check credentials."
        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

    def __enter__(self):
        """Context manager вход"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager выход"""
        self.disconnect()


if __name__ == "__main__":
    # Пример использования
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 5:
        print("Usage: python imap_client.py <server> <port> <username> <password>")
        sys.exit(1)

    server, port, username, password = sys.argv[1:5]

    client = IMAPClient(server, int(port), username, password)

    success, message = client.test_connection()
    print(f"Test result: {message}")

    if success:
        with client:
            client.select_folder("INBOX")
            uids = client.get_new_message_uids()

            if uids:
                print(f"\nFetching first message (UID: {uids[0]})...")
                msg = client.fetch_message(uids[0])
                if msg:
                    print(f"Subject: {msg['subject']}")
                    print(f"From: {msg['from']}")
                    print(f"Date: {msg['date']}")
                    print(f"Has attachments: {msg['has_attachments']}")
                    print(f"Body preview: {msg['body_text'][:200]}...")
