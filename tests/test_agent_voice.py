import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import handle_private_agent_voice
from bot.voice_transcription import VoiceTranscriptionError, transcribe_audio_bytes, transcribe_telegram_voice


class VoiceTranscriptionTest(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_audio_bytes_returns_normalized_text(self):
        fake_client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(
                    create=AsyncMock(return_value="  проверь   бланки   по сухому логу  ")
                )
            ),
            close=AsyncMock(),
        )

        with patch("bot.voice_transcription.AsyncOpenAI", return_value=fake_client):
            result = await transcribe_audio_bytes(b"voice-bytes")

        self.assertEqual(result, "проверь бланки по сухому логу")
        create_kwargs = fake_client.audio.transcriptions.create.await_args.kwargs
        self.assertEqual(create_kwargs["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(create_kwargs["language"], "ru")
        self.assertEqual(create_kwargs["response_format"], "text")
        fake_client.close.assert_awaited_once()

    async def test_transcribe_telegram_voice_downloads_file_before_transcription(self):
        bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="voice/path.ogg")),
            download_file=AsyncMock(return_value=BytesIO(b"voice-payload")),
        )
        message = SimpleNamespace(
            bot=bot,
            voice=SimpleNamespace(file_id="voice-id", mime_type="audio/ogg"),
            audio=None,
        )

        with patch("bot.voice_transcription.transcribe_audio_bytes", AsyncMock(return_value="проверь стоп-лист")) as mocked_transcribe:
            result = await transcribe_telegram_voice(message)

        self.assertEqual(result, "проверь стоп-лист")
        bot.get_file.assert_awaited_once_with("voice-id")
        bot.download_file.assert_awaited_once_with("voice/path.ogg")
        mocked_transcribe.assert_awaited_once_with(
            b"voice-payload",
            file_name="voice.ogg",
            mime_type="audio/ogg",
        )


class _DummyServiceMessage:
    def __init__(self) -> None:
        self.edits: list[str] = []

    async def edit_text(self, text: str, **_: object) -> None:
        self.edits.append(text)


class _DummyVoiceMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.voice = SimpleNamespace(file_id="voice-id", mime_type="audio/ogg")
        self.answers: list[str] = []
        self.service_messages: list[_DummyServiceMessage] = []

    async def answer(self, text: str, **_: object) -> _DummyServiceMessage:
        self.answers.append(text)
        service_message = _DummyServiceMessage()
        self.service_messages.append(service_message)
        return service_message


class AgentVoiceHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_handle_private_agent_voice_transcribes_and_dispatches(self):
        message = _DummyVoiceMessage()

        with patch(
            "bot.data_agent_handlers.transcribe_telegram_voice",
            AsyncMock(return_value="покажи бланки по сухому логу"),
        ), patch(
            "bot.data_agent_handlers._dispatch_agent_request",
            AsyncMock(),
        ) as mocked_dispatch:
            await handle_private_agent_voice(message, state=SimpleNamespace())

        self.assertEqual(message.answers, ["Распознаю голосовое сообщение..."])
        self.assertEqual(
            message.service_messages[0].edits,
            ["Распознал запрос:\nпокажи бланки по сухому логу"],
        )
        mocked_dispatch.assert_awaited_once_with(message, "покажи бланки по сухому логу")

    async def test_handle_private_agent_voice_returns_friendly_error_on_transcription_failure(self):
        message = _DummyVoiceMessage()

        with patch(
            "bot.data_agent_handlers.transcribe_telegram_voice",
            AsyncMock(side_effect=VoiceTranscriptionError("failed")),
        ), patch(
            "bot.data_agent_handlers._dispatch_agent_request",
            AsyncMock(),
        ) as mocked_dispatch:
            await handle_private_agent_voice(message, state=SimpleNamespace())

        self.assertEqual(message.answers, ["Распознаю голосовое сообщение..."])
        self.assertEqual(
            message.service_messages[0].edits,
            ["Не удалось распознать голосовое сообщение. Попробуйте ещё раз или отправьте запрос текстом."],
        )
        mocked_dispatch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
