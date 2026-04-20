import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _dispatch_agent_request, handle_private_agent_message


class _DummyMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class AgentRequestDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_long_request_sends_start_notice_and_schedules_background(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._schedule_background_agent_request") as mocked_schedule:
            await _dispatch_agent_request(message, "проверь стоп-лист по точке Екатеринбург, Ленина 147")

        self.assertEqual(message.answers, ["⏳ Принял запрос. Собираю отчёт, это может занять пару минут."])
        mocked_schedule.assert_called_once_with(
            message,
            "проверь стоп-лист по точке Екатеринбург, Ленина 147",
            send_progress=False,
        )

    async def test_short_request_runs_immediately_without_extra_messages(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._send_agent_request", AsyncMock()) as mocked_send:
            await _dispatch_agent_request(message, "какие системы подключены")

        self.assertEqual(message.answers, [])
        mocked_send.assert_awaited_once_with(message, "какие системы подключены")

    async def test_systems_free_text_opens_systems_summary_directly(self):
        message = _DummyMessage("какие системы подключены")

        with patch("bot.data_agent_handlers._send_systems_summary", AsyncMock()) as mocked_summary:
            with patch("bot.data_agent_handlers._dispatch_agent_request", AsyncMock()) as mocked_dispatch:
                await handle_private_agent_message(message, state=SimpleNamespace())

        mocked_summary.assert_awaited_once_with(message)
        mocked_dispatch.assert_not_awaited()

    async def test_connect_system_free_text_still_goes_to_agent(self):
        message = _DummyMessage("подключить систему")

        with patch("bot.data_agent_handlers._send_systems_summary", AsyncMock()) as mocked_summary:
            with patch("bot.data_agent_handlers._dispatch_agent_request", AsyncMock()) as mocked_dispatch:
                await handle_private_agent_message(message, state=SimpleNamespace())

        mocked_summary.assert_not_awaited()
        mocked_dispatch.assert_awaited_once_with(message, "подключить систему")


if __name__ == "__main__":
    unittest.main()
