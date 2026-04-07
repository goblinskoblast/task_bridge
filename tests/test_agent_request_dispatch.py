import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _build_agent_processing_notice, _dispatch_agent_request


class _DummyMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class AgentRequestDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_long_request_sends_notice_and_schedules_background_work(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._schedule_background_agent_request") as mocked_schedule:
            await _dispatch_agent_request(message, "проверь стоп-лист по точке Екатеринбург, Ленина 147")

        self.assertEqual(len(message.answers), 1)
        self.assertIn("Агент уже начал обработку", message.answers[0])
        self.assertIn("Ничего дополнительно отправлять не нужно", message.answers[0])
        mocked_schedule.assert_called_once()

    async def test_short_request_runs_immediately_without_notice(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._send_agent_request", AsyncMock()) as mocked_send:
            await _dispatch_agent_request(message, "какие системы подключены")

        self.assertEqual(message.answers, [])
        mocked_send.assert_awaited_once_with(message, "какие системы подключены")

    def test_processing_notice_guides_user(self):
        text = _build_agent_processing_notice("проверь бланки")
        self.assertIn("Агент уже начал обработку", text)
        self.assertIn("как только результат будет готов, я пришлю его сюда", text.lower())


if __name__ == "__main__":
    unittest.main()
