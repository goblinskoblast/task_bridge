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
from bot.handlers import _build_help_message, _build_main_reply_keyboard, _build_welcome_message


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
                "📍 Точки",
                "📡 Мониторинги",
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

    def test_reports_submenu_is_now_navigation_only(self):
        keyboard = _build_agent_reports_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("📍 Точки", texts)
        self.assertIn("📡 Мониторинги", texts)
        self.assertIn("↩️ В меню агента", texts)
        self.assertNotIn("🚫 Стоп-лист", texts)
        self.assertNotIn("🧾 Бланки сейчас", texts)
        self.assertNotIn("⭐ Отзывы за сутки", texts)

    def test_settings_submenu_contains_settings_actions_and_home(self):
        keyboard = _build_agent_settings_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("➕ Подключить систему", texts)
        self.assertIn("💬 Чаты отчётов", texts)
        self.assertIn("📡 Мониторинги", texts)
        self.assertIn("↩️ В меню агента", texts)

    def test_point_actions_keyboard_keeps_only_point_management_actions(self):
        point = SimpleNamespace(id=7, report_delivery_enabled=False)
        keyboard = _build_point_actions_keyboard(point)
        callback_data = _flatten_callback_data(keyboard)

        self.assertIn("agent_open", callback_data)
        self.assertIn("agent_show_points", callback_data)
        self.assertIn("agent_point:delete:7", callback_data)
        self.assertIn("agent_point_delivery:7", callback_data)
        self.assertNotIn("agent_point_report:7:stoplist", callback_data)
        self.assertNotIn("agent_point_report:7:blanks_current", callback_data)
        self.assertNotIn("agent_point_report:7:reviews_day", callback_data)

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

    def test_help_message_prefers_free_text_over_legacy_report_commands(self):
        text = _build_help_message()

        self.assertIn("пришли стоп-лист", text)
        self.assertIn("покажи мониторинги", text)
        self.assertNotIn("/reviews", text)
        self.assertNotIn("/stoplist", text)
        self.assertNotIn("/blanks", text)
        self.assertNotIn("/monitors", text)

    def test_main_welcome_message_mentions_free_text_point_flow(self):
        text = _build_welcome_message(is_first_auth=False, pending_count=0)

        self.assertIn("/addpoint", text)
        self.assertIn("обычным сообщением", text)
        self.assertNotIn("быстрых отчётов", text)


if __name__ == "__main__":
    unittest.main()
