import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _dispatch_agent_request


class _DummyMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class AgentRequestDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_long_request_schedules_background_without_start_notice(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._schedule_background_agent_request") as mocked_schedule:
            await _dispatch_agent_request(message, "проверь стоп-лист по точке Екатеринбург, Ленина 147")

        self.assertEqual(message.answers, [])
        mocked_schedule.assert_called_once_with(message, "проверь стоп-лист по точке Екатеринбург, Ленина 147")

    async def test_short_request_runs_immediately_without_extra_messages(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._send_agent_request", AsyncMock()) as mocked_send:
            await _dispatch_agent_request(message, "какие системы подключены")

        self.assertEqual(message.answers, [])
        mocked_send.assert_awaited_once_with(message, "какие системы подключены")


if __name__ == "__main__":
    unittest.main()
