import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.handlers import AGENT_MAIN_BUTTON_TEXT, PANEL_BUTTON_TEXT, cmd_start


def _flatten_inline_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _flatten_reply_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.keyboard for button in row]


class _DummyActionableQuery:
    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _DummyDbSession:
    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def query(self, *_args, **_kwargs):
        return object()

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class _DummyMessage:
    def __init__(self) -> None:
        self.bot = SimpleNamespace()
        self.from_user = SimpleNamespace(
            id=17,
            username="tester",
            first_name="Tester",
            last_name=None,
            is_bot=False,
        )
        self.answers: list[dict] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append({"text": text, **kwargs})


class StartShortcutsFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_start_sends_shortcuts_then_reply_menu(self):
        message = _DummyMessage()
        db = _DummyDbSession()
        user = SimpleNamespace(id=42, telegram_id=17, username="tester")

        with patch("bot.handlers.get_db_session", return_value=db):
            with patch("bot.handlers.get_or_create_user", AsyncMock(return_value=user)):
                with patch("bot.handlers.actionable_tasks", return_value=_DummyActionableQuery()):
                    with patch("bot.handlers.build_taskbridge_webapp_url", return_value="https://example.com/webapp"):
                        await cmd_start(message)

        self.assertTrue(db.closed)
        self.assertEqual(len(message.answers), 2)

        welcome = message.answers[0]
        self.assertEqual(_flatten_inline_texts(welcome["reply_markup"]), [PANEL_BUTTON_TEXT, AGENT_MAIN_BUTTON_TEXT])
        self.assertEqual(welcome["reply_markup"].inline_keyboard[0][0].web_app.url, "https://example.com/webapp")
        self.assertEqual(welcome["reply_markup"].inline_keyboard[1][0].callback_data, "agent_open")
        self.assertEqual(welcome["parse_mode"], "HTML")

        menu_notice = message.answers[1]
        self.assertEqual(menu_notice["text"], "Меню внизу.")
        self.assertIn(PANEL_BUTTON_TEXT, _flatten_reply_texts(menu_notice["reply_markup"]))
        self.assertIn(AGENT_MAIN_BUTTON_TEXT, _flatten_reply_texts(menu_notice["reply_markup"]))


if __name__ == "__main__":
    unittest.main()
