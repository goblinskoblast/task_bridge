import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import (
    _build_agent_entry_keyboard,
    _build_agent_entry_text,
    _build_legacy_quick_report_hint,
    _build_agent_reports_menu_keyboard,
    _build_agent_settings_menu_keyboard,
    _build_point_actions_keyboard,
    _build_report_chat_keyboard,
    _build_slim_main_reply_keyboard,
    callback_agent_quick_stoplist,
    _send_monitors_summary,
    cmd_delpoint,
    cmd_unmonitor,
    open_monitors_from_button,
    open_quick_reports_from_button,
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
        self.assertEqual(keyboard.input_field_placeholder, "Напишите задачу или запрос агенту")

    def test_agent_root_keyboard_for_ready_user_has_only_main_sections(self):
        texts = _flatten_inline_texts(_build_agent_entry_keyboard(has_system=True, has_points=True))

        self.assertEqual(
            texts,
            [
                "📍 Точки",
                "📡 Что включено",
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

    def test_agent_entry_text_promotes_monitor_free_text_summary(self):
        text = _build_agent_entry_text(has_system=True, has_points=True)
        self.assertIn("что у меня включено", text)
        self.assertIn("присылай бланки", text)

    def test_reports_submenu_is_now_navigation_only(self):
        keyboard = _build_agent_reports_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("📍 Точки", texts)
        self.assertIn("📡 Что включено", texts)
        self.assertIn("↩️ В меню агента", texts)
        self.assertNotIn("🚫 Стоп-лист", texts)
        self.assertNotIn("🧾 Бланки сейчас", texts)
        self.assertNotIn("⭐ Отзывы за сутки", texts)

    def test_settings_submenu_contains_only_settings_actions_and_home(self):
        keyboard = _build_agent_settings_menu_keyboard()
        texts = _flatten_inline_texts(keyboard)

        self.assertIn("➕ Подключить систему", texts)
        self.assertIn("💬 Чаты отчётов", texts)
        self.assertNotIn("📡 Что включено", texts)
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
        self.assertEqual(keyboard.input_field_placeholder, "Напишите задачу или запрос агенту")

    def test_help_message_prefers_free_text_over_legacy_report_commands(self):
        text = _build_help_message()

        self.assertIn("пришли стоп-лист", text)
        self.assertIn("покажи мониторинги", text)
        self.assertIn("добавить точку там", text)
        self.assertNotIn("/reviews", text)
        self.assertNotIn("/stoplist", text)
        self.assertNotIn("/blanks", text)
        self.assertNotIn("/monitors", text)
        self.assertNotIn("/addpoint", text)

    def test_main_welcome_message_mentions_free_text_point_flow(self):
        text = _build_welcome_message(is_first_auth=False, pending_count=0)

        self.assertIn("открыть агента, сохранить точку", text)
        self.assertIn("обычным сообщением", text)
        self.assertNotIn("быстрых отчётов", text)


class LegacyCommandUxTest(unittest.IsolatedAsyncioTestCase):
    class DummyMessage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.from_user = SimpleNamespace(id=17)
            self.answers: list[str] = []
            self.reply_markups: list[object] = []

        async def answer(self, text: str, **kwargs: object) -> None:
            self.answers.append(text)
            self.reply_markups.append(kwargs.get("reply_markup"))

    class DummyCallback:
        def __init__(self) -> None:
            self.message = LegacyCommandUxTest.DummyMessage("")
            self.from_user = SimpleNamespace(id=17)
            self.answers: list[str | None] = []

        async def answer(self, text: str | None = None, **kwargs: object) -> None:
            self.answers.append(text)

    class DummyState:
        def __init__(self) -> None:
            self.clear_count = 0

        async def clear(self) -> None:
            self.clear_count += 1

    def test_legacy_quick_report_hint_points_to_free_text(self):
        text = _build_legacy_quick_report_hint("stoplist")

        self.assertIn("обычным сообщением", text)
        self.assertIn("пришли стоп-лист", text)
        self.assertNotIn("Пришлите только точку", text)

    async def test_legacy_quick_report_callback_no_longer_prompts_point_keyboard(self):
        callback = self.DummyCallback()
        state = self.DummyState()

        await callback_agent_quick_stoplist(callback, state)

        self.assertEqual(state.clear_count, 1)
        self.assertEqual(len(callback.message.answers), 1)
        self.assertIn("обычным сообщением", callback.message.answers[0])
        self.assertIn("пришли стоп-лист", callback.message.answers[0])
        self.assertEqual(_flatten_inline_texts(callback.message.reply_markups[-1]), ["↩️ В меню агента"])

    async def test_legacy_quick_reports_reply_button_opens_text_examples(self):
        message = self.DummyMessage("⚡ Быстрые отчёты")
        state = self.DummyState()

        with patch("bot.data_agent_handlers._refresh_private_main_menu", AsyncMock()) as mocked_refresh:
            with patch("bot.data_agent_handlers._send_agent_reports_menu", AsyncMock()) as mocked_reports:
                await open_quick_reports_from_button(message, state)

        self.assertEqual(state.clear_count, 1)
        mocked_refresh.assert_awaited_once()
        mocked_reports.assert_awaited_once_with(message)

    async def test_legacy_monitors_reply_button_opens_active_summary(self):
        message = self.DummyMessage("📡 Мониторы")
        state = self.DummyState()

        with patch("bot.data_agent_handlers._refresh_private_main_menu", AsyncMock()) as mocked_refresh:
            with patch("bot.data_agent_handlers._send_monitors_summary", AsyncMock()) as mocked_monitors:
                await open_monitors_from_button(message, state)

        self.assertEqual(state.clear_count, 1)
        mocked_refresh.assert_awaited_once()
        mocked_monitors.assert_awaited_once_with(message)

    async def test_unmonitor_without_id_points_to_free_text_disable(self):
        message = self.DummyMessage("/unmonitor")

        await cmd_unmonitor(message)

        self.assertEqual(len(message.answers), 1)
        self.assertIn("обычным текстом", message.answers[0])
        self.assertIn("не присылай бланки", message.answers[0])
        self.assertNotIn("/unmonitor 12", message.answers[0])

    async def test_delpoint_without_id_points_to_point_menu(self):
        message = self.DummyMessage("/delpoint")

        await cmd_delpoint(message)

        self.assertEqual(len(message.answers), 1)
        self.assertIn("Агент → Точки", message.answers[0])
        self.assertIn("Удалить", message.answers[0])
        self.assertNotIn("/delpoint 3", message.answers[0])

    async def test_unmonitor_failure_hides_internal_reason(self):
        message = self.DummyMessage("/unmonitor 12")

        with patch(
            "bot.data_agent_handlers.data_agent_client.delete_monitor",
            AsyncMock(return_value={"success": False, "error": "Page.evaluate failed"}),
        ) as mocked_delete:
            await cmd_unmonitor(message)

        mocked_delete.assert_not_awaited()
        self.assertEqual(len(message.answers), 1)
        self.assertIn("обычным текстом", message.answers[0])
        self.assertIn("не присылай бланки", message.answers[0])
        self.assertNotIn("Page.evaluate", message.answers[0])
        self.assertNotIn("#12", message.answers[0])

    async def test_monitors_summary_has_only_home_action_when_empty(self):
        message = self.DummyMessage("покажи мониторинги")

        with patch("bot.data_agent_handlers.data_agent_client.list_monitors", AsyncMock(return_value=[])):
            await _send_monitors_summary(message)

        self.assertEqual(_flatten_inline_texts(message.reply_markups[-1]), ["↩️ В меню агента"])
        self.assertNotIn("➕ Подключить систему", _flatten_inline_texts(message.reply_markups[-1]))

    async def test_monitors_summary_has_only_home_action_when_present(self):
        message = self.DummyMessage("покажи мониторинги")
        monitor = {
            "monitor_type": "blanks",
            "point_name": "Сухой Лог, Белинского 40",
            "interval_label": "каждые 3 часа",
            "window_label": "с 10:00 до 22:00 по Екатеринбургу",
            "status_label": "красных зон нет",
            "last_checked_label": "сегодня в 22:00",
            "next_check_label": "завтра в 10:00",
            "last_event_title": "Последнее уведомление",
            "last_event_label": "пока не было",
            "behavior_label": "сразу сообщу, если появится красная зона",
        }

        with patch("bot.data_agent_handlers.data_agent_client.list_monitors", AsyncMock(return_value=[monitor])):
            await _send_monitors_summary(message)

        self.assertIn("Активные мониторинги", message.answers[-1])
        self.assertIn("Сухой Лог, Белинского 40", message.answers[-1])
        self.assertEqual(_flatten_inline_texts(message.reply_markups[-1]), ["↩️ В меню агента"])
        self.assertNotIn("💬 Чаты отчётов", _flatten_inline_texts(message.reply_markups[-1]))


if __name__ == "__main__":
    unittest.main()
