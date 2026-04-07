import logging
from typing import Optional

from .encryption import decrypt_password, encrypt_password

logger = logging.getLogger(__name__)

EMAIL_SECRET_PREFIX = "enc:"


def is_encrypted_email_secret(secret: Optional[str]) -> bool:
    return bool(secret) and secret.startswith(EMAIL_SECRET_PREFIX)


def encrypt_email_secret(secret: Optional[str]) -> str:
    if not secret:
        return ""
    if is_encrypted_email_secret(secret):
        return secret

    try:
        return f"{EMAIL_SECRET_PREFIX}{encrypt_password(secret)}"
    except Exception as exc:
        logger.warning("Email secret encryption is unavailable, storing transitional plaintext secret: %s", exc)
        return secret


def decrypt_email_secret(secret: Optional[str]) -> str:
    if not secret:
        return ""
    if not is_encrypted_email_secret(secret):
        return secret

    encrypted_payload = secret[len(EMAIL_SECRET_PREFIX):]
    return decrypt_password(encrypted_payload)
