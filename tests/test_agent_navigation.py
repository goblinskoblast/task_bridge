import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _build_point_actions_keyboard, _build_report_chat_keyboard
from bot.handlers import _build_main_reply_keyboard


def _flatten_button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.keyboard for button in row]


def _flatten_callback_data(keyboard) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if getattr(button, "callback_data", None)
    ]


class AgentNavigationTest(unittest.TestCase):
    def test_main_reply_keyboard_hides_duplicate_agent_buttons(self):
        keyboard = _build_main_reply_keyboard("https://example.com/webapp")
        texts = _flatten_button_texts(keyboard)

        self.assertIn("🤖 Агент", texts)
        self.assertNotIn("⚡ Быстрые отчёты", texts)
        self.assertNotIn("📡 Мониторы", texts)

    def test_point_actions_keyboard_has_agent_home_button(self):
        point = SimpleNamespace(id=7, report_delivery_enabled=False)
        keyboard = _build_point_actions_keyboard(point)

        self.assertIn("agent_open", _flatten_callback_data(keyboard))

    def test_report_chat_keyboard_has_agent_home_button(self):
        chat = SimpleNamespace(chat_id=-1001, title="Отчёты", username=None)
        keyboard = _build_report_chat_keyboard([chat], selected_chat_id=None)

        self.assertIn("agent_open", _flatten_callback_data(keyboard))


if __name__ == "__main__":
    unittest.main()
