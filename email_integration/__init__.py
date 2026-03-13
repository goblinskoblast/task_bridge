"""
Email Integration Package для TaskBridge

Этот пакет содержит функциональность для интеграции с email через IMAP:
- Подключение к email аккаунтам
- Чтение и парсинг писем
- AI анализ писем и создание задач
- Шифрование credentials
"""

from .encryption import encrypt_password, decrypt_password, generate_encryption_key

__all__ = [
    'encrypt_password',
    'decrypt_password',
    'generate_encryption_key',
]
