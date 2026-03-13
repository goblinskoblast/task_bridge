"""
Модуль для шифрования и дешифрования паролей email аккаунтов
"""
import os
import logging
from cryptography.fernet import Fernet
from typing import Optional

logger = logging.getLogger(__name__)


class PasswordEncryption:
    """Класс для шифрования и дешифрования паролей"""

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Инициализация с ключом шифрования

        Args:
            encryption_key: Ключ шифрования в base64. Если не указан, берется из переменной окружения.
        """
        if encryption_key is None:
            encryption_key = os.getenv("EMAIL_ENCRYPTION_KEY")

        if not encryption_key:
            raise ValueError(
                "EMAIL_ENCRYPTION_KEY not found. Please set it in environment variables.\n"
                "Generate a new key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        try:
            self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        except Exception as e:
            logger.error(f"Failed to initialize encryption cipher: {e}")
            raise ValueError(f"Invalid encryption key: {e}")

    def encrypt(self, password: str) -> str:
        """
        Шифрование пароля

        Args:
            password: Пароль в открытом виде

        Returns:
            Зашифрованный пароль в виде строки
        """
        if not password:
            raise ValueError("Password cannot be empty")

        try:
            encrypted_bytes = self.cipher.encrypt(password.encode('utf-8'))
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to encrypt password: {e}")
            raise RuntimeError(f"Encryption failed: {e}")

    def decrypt(self, encrypted_password: str) -> str:
        """
        Дешифрование пароля

        Args:
            encrypted_password: Зашифрованный пароль

        Returns:
            Пароль в открытом виде
        """
        if not encrypted_password:
            raise ValueError("Encrypted password cannot be empty")

        try:
            decrypted_bytes = self.cipher.decrypt(encrypted_password.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to decrypt password: {e}")
            raise RuntimeError(f"Decryption failed: {e}")


# Глобальный экземпляр для использования в приложении
_encryptor: Optional[PasswordEncryption] = None


def get_encryptor() -> PasswordEncryption:
    """Получить глобальный экземпляр PasswordEncryption"""
    global _encryptor
    if _encryptor is None:
        _encryptor = PasswordEncryption()
    return _encryptor


def encrypt_password(password: str) -> str:
    """Удобная функция для шифрования пароля"""
    return get_encryptor().encrypt(password)


def decrypt_password(encrypted_password: str) -> str:
    """Удобная функция для дешифрования пароля"""
    return get_encryptor().decrypt(encrypted_password)


def generate_encryption_key() -> str:
    """Генерация нового ключа шифрования"""
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    # Генерация ключа для .env файла
    print("Generated encryption key (add to your .env file):")
    print(f"EMAIL_ENCRYPTION_KEY={generate_encryption_key()}")

    # Тестирование шифрования
    print("\nTesting encryption...")
    test_password = "MySecurePassword123!"

    # Нужно установить временный ключ для теста
    test_key = generate_encryption_key()
    encryptor = PasswordEncryption(test_key)

    encrypted = encryptor.encrypt(test_password)
    print(f"Original: {test_password}")
    print(f"Encrypted: {encrypted}")

    decrypted = encryptor.decrypt(encrypted)
    print(f"Decrypted: {decrypted}")

    assert test_password == decrypted, "Encryption/Decryption test failed!"
    print("\n✓ Encryption test passed!")
