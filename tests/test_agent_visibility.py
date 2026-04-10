import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _send_agent_request, cmd_agentdebug


class _DummyMessage:
    def __init__(self, user_id: int = 17) -> None:
        self.from_user = SimpleNamespace(id=user_id, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class AgentVisibilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_report_response_is_neutral_without_debug_block(self):
        message = _DummyMessage()
        result = {
            "status": "failed",
            "scenario": "stoplist_report",
            "answer": "Стоп-лист сейчас не удалось собрать. Причина: Не удалось подтвердить выбор точки.",
            "debug_summary": "Trace: abc\nСтатус: failed",
        }

        with patch("bot.data_agent_handlers.data_agent_client.chat", AsyncMock(return_value=result)):
            await _send_agent_request(message, "собери стоп-лист по точке")

        self.assertEqual(
            message.answers,
            ["Стоп-лист сейчас не удалось собрать. Причина: Не удалось подтвердить выбор точки."],
        )

    async def test_non_developer_cannot_use_agentdebug(self):
        message = _DummyMessage(user_id=17)

        with patch("bot.data_agent_handlers.DEVELOPER_TELEGRAM_ID", 99):
            await cmd_agentdebug(message)

        self.assertEqual(message.answers, ["Команда недоступна."])

    async def test_developer_can_use_agentdebug(self):
        message = _DummyMessage(user_id=17)

        with patch("bot.data_agent_handlers.DEVELOPER_TELEGRAM_ID", 17), patch(
            "bot.data_agent_handlers._send_agent_debug_message",
            AsyncMock(),
        ) as mocked_send_debug:
            await cmd_agentdebug(message)

        self.assertEqual(message.answers, [])
        mocked_send_debug.assert_awaited_once_with(message, 17)


if __name__ == "__main__":
    unittest.main()
