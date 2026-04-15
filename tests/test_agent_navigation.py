import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import (
    _build_agent_entry_keyboard,
    _build_agent_entry_text,
    _build_agent_reports_menu_keyboard,
    _build_agent_settings_menu_keyboard,
    _build_point_actions_keyboard,
    _build_report_chat_keyboard,
    _build_slim_main_reply_keyboard,
)
from bot.handlers import _build_main_reply_keyboard


def _flatten_button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.keyboard for button in row]


def _flatten_inline_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


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

    def test_agent_root_keyboard_for_ready_user_has_only_main_sections(self):
        texts = _flatten_inline_texts(_build_agent_entry_keyboard(has_system=True, has_points=True))

        self.assertEqual(
            texts,
            [
                "📊 Отчёты",
                "📍 Точки",
                "⚙️ Настройки",
            ],
        )

    def test_agent_root_keyboard_without_system_leads_only_to_connect(self):
        texts = _flatten_inline_texts(_build_agent_entry_keyboard(has_system=False, has_points=False))
        self.assertEqual(texts, ["➕ Подключить систему"])

    def test_agent_root_keyboard_without_points_leads_to_add_point(self):
        texts = _flatten_inline_texts(_build_agent_entry_keyboard(has_system=True, has_points=False))
        self.assertEqual(
            texts,
            [
                "➕ Добавить точку",
                "⚙️ Настройки",
            ],
        )

    def test_agent_entry_text_without_system_is_linear(self):
        text = _build_agent_entry_text(has_system=False, has_points=False)
        self.assertIn("Сначала подключите систему Italian Pizza.", text)

    def test_agent_entry_text_without_points_is_linear(self):
        text = _build_agent_entry_text(has_system=True, has_points=False)
        self.assertIn("Теперь добавьте первую точку.", text)

    def test_reports_submenu_contains_report_actions_and_home(self):
        keyboard = _build_agent_reports_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("⭐ Отзывы за сутки", texts)
        self.assertIn("📈 Отзывы за неделю", texts)
        self.assertIn("🚫 Стоп-лист", texts)
        self.assertIn("🧾 Бланки сейчас", texts)
        self.assertIn("🕒 Бланки 12 часов", texts)
        self.assertIn("↩️ В меню агента", texts)

    def test_settings_submenu_contains_settings_actions_and_home(self):
        keyboard = _build_agent_settings_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("➕ Подключить систему", texts)
        self.assertIn("💬 Чаты отчётов", texts)
        self.assertIn("📡 Мониторинги", texts)
        self.assertIn("↩️ В меню агента", texts)

    def test_point_actions_keyboard_has_agent_home_button(self):
        point = SimpleNamespace(id=7, report_delivery_enabled=False)
        keyboard = _build_point_actions_keyboard(point)

        self.assertIn("agent_open", _flatten_callback_data(keyboard))

    def test_report_chat_keyboard_has_agent_home_button(self):
        chat = SimpleNamespace(chat_id=-1001, title="Отчёты", username=None)
        keyboard = _build_report_chat_keyboard([chat], selected_chat_id=None)

        self.assertIn("agent_open", _flatten_callback_data(keyboard))

    def test_slim_main_reply_keyboard_has_no_duplicate_buttons(self):
        keyboard = _build_slim_main_reply_keyboard("https://example.com/webapp")
        texts = _flatten_button_texts(keyboard)

        self.assertIn("🤖 Агент", texts)
        self.assertIn("💬 Поддержка", texts)
        self.assertIn("❓ Помощь", texts)
        self.assertNotIn("⚡ Быстрые отчёты", texts)
        self.assertNotIn("📡 Мониторы", texts)


if __name__ == "__main__":
    unittest.main()
