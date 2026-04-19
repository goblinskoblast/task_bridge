import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_client import DataAgentTimeoutError
from bot.data_agent_handlers import _send_agent_request, connect_waiting_for_password


class _DummyMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=17, username="tester", first_name="Tester")
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class _EditableMessage:
    def __init__(self) -> None:
        self.edits: list[str] = []

    async def edit_text(self, text: str, **_: object) -> None:
        self.edits.append(text)


class _DummyConnectMessage(_DummyMessage):
    def __init__(self) -> None:
        super().__init__()
        self.text = "secret-password"
        self.deleted = False
        self.waiting_messages: list[_EditableMessage] = []

    async def delete(self) -> None:
        self.deleted = True

    async def answer(self, text: str, **_: object) -> _EditableMessage:
        self.answers.append(text)
        waiting = _EditableMessage()
        self.waiting_messages.append(waiting)
        return waiting


class _DummyState:
    def __init__(self) -> None:
        self.cleared = False

    async def get_data(self) -> dict[str, str]:
        return {
            "url": "https://portal.example.com",
            "username": "manager",
        }

    async def clear(self) -> None:
        self.cleared = True


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
                "Сейчас не удалось обработать запрос. Попробуйте ещё раз чуть позже.",
            ],
        )


    async def test_background_long_request_uses_extended_timeout_without_retry(self):
        message = _DummyMessage()

        with patch("bot.data_agent_handlers.data_agent_client.chat", AsyncMock(return_value={"answer": "ok"})) as mocked_chat:
            await _send_agent_request(
                message,
                "Покажи мне бланки загрузки по всем добавленным точкам",
                send_progress=False,
            )

        self.assertEqual(message.answers, ["ok"])
        self.assertEqual(mocked_chat.await_count, 1)
        self.assertEqual(mocked_chat.await_args.kwargs.get("retry_attempts"), 1)
        self.assertGreaterEqual(mocked_chat.await_args.kwargs.get("timeout_seconds") or 0, 300)

    async def test_connect_failure_hides_internal_backend_error(self):
        message = _DummyConnectMessage()
        state = _DummyState()

        with patch(
            "bot.data_agent_handlers.data_agent_client.connect_system",
            AsyncMock(return_value={"success": False, "error": "Page.evaluate failed DATA_AGENT_URL"}),
        ):
            await connect_waiting_for_password(message, state)

        self.assertTrue(state.cleared)
        self.assertEqual(message.answers, ["⏳ Проверяю подключение системы..."])
        self.assertEqual(
            message.waiting_messages[-1].edits,
            ["Не удалось подключить систему. Проверьте адрес и логин/пароль, затем попробуйте ещё раз."],
        )
        self.assertNotIn("Page.evaluate", message.waiting_messages[-1].edits[0])
        self.assertNotIn("DATA_AGENT_URL", message.waiting_messages[-1].edits[0])

    async def test_connect_exception_hides_internal_service_names(self):
        message = _DummyConnectMessage()
        state = _DummyState()

        with patch(
            "bot.data_agent_handlers.data_agent_client.connect_system",
            AsyncMock(side_effect=RuntimeError("INTERNAL_API_URL is missing")),
        ):
            await connect_waiting_for_password(message, state)

        self.assertEqual(message.waiting_messages[-1].edits, ["Не удалось проверить подключение. Попробуйте ещё раз чуть позже."])
        self.assertNotIn("INTERNAL_API_URL", message.waiting_messages[-1].edits[0])
        self.assertNotIn("сервис", message.waiting_messages[-1].edits[0].lower())


if __name__ == "__main__":
    unittest.main()
