import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_client import DataAgentTimeoutError
from bot.data_agent_handlers import _send_agent_request


class _DummyMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class AgentRequestErrorsTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_error_returns_specific_message(self):
        message = _DummyMessage()
        timeout_error = DataAgentTimeoutError(
            "timeout",
            user_message="Агент не успел ответить. Запрос выполняется слишком долго, попробуйте повторить чуть позже.",
        )

        with patch("bot.data_agent_handlers.data_agent_client.chat", AsyncMock(side_effect=timeout_error)):
            await _send_agent_request(message, "проверь бланки")

        self.assertEqual(
            message.answers,
            [
                "⏳ Принял запрос. Собираю отчёт, это может занять пару минут.",
                "Агент не успел ответить. Запрос выполняется слишком долго, попробуйте повторить чуть позже.",
            ],
        )

    async def test_unexpected_error_keeps_generic_message(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers.data_agent_client.chat", AsyncMock(side_effect=RuntimeError("boom"))):
            await _send_agent_request(message, "проверь стоп-лист")

        self.assertEqual(
            message.answers,
            [
                "⏳ Принял запрос. Собираю отчёт, это может занять пару минут.",
                "Агент сейчас недоступен. Проверьте отдельный сервис и попробуйте ещё раз.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
