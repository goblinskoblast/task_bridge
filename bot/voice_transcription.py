from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from aiogram.types import Message
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_TRANSCRIPTION_MODEL

logger = logging.getLogger(__name__)


class VoiceTranscriptionError(RuntimeError):
    pass


def _normalize_transcription_text(value: Any) -> str:
    text = value if isinstance(value, str) else getattr(value, "text", str(value or ""))
    return " ".join(str(text).strip().split())


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    file_name: str = "voice.ogg",
    mime_type: str = "audio/ogg",
) -> str:
    if not OPENAI_API_KEY:
        raise VoiceTranscriptionError("OpenAI API key is not configured")
    if not audio_bytes:
        raise VoiceTranscriptionError("Audio payload is empty")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        response = await client.audio.transcriptions.create(
            file=(file_name, audio_bytes, mime_type),
            model=OPENAI_TRANSCRIPTION_MODEL,
            language="ru",
            response_format="text",
            temperature=0,
            prompt="Это голосовой запрос пользователя к Telegram-агенту TaskBridge.",
        )
    except Exception as exc:
        logger.error("Voice transcription failed: %s", exc, exc_info=True)
        raise VoiceTranscriptionError("Voice transcription failed") from exc
    finally:
        await client.close()

    text = _normalize_transcription_text(response)
    if not text:
        raise VoiceTranscriptionError("Voice transcription is empty")
    return text


async def transcribe_telegram_voice(message: Message) -> str:
    media = getattr(message, "voice", None) or getattr(message, "audio", None)
    if not media:
        raise VoiceTranscriptionError("Message does not contain voice or audio")

    telegram_file = await message.bot.get_file(media.file_id)
    downloaded = await message.bot.download_file(telegram_file.file_path)

    if isinstance(downloaded, BytesIO):
        payload = downloaded.getvalue()
    elif hasattr(downloaded, "read"):
        payload = downloaded.read()
    else:
        payload = bytes(downloaded)

    file_name = getattr(media, "file_name", None) or "voice.ogg"
    mime_type = getattr(media, "mime_type", None) or "audio/ogg"
    return await transcribe_audio_bytes(payload, file_name=file_name, mime_type=mime_type)
