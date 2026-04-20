import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import (
    AGENT_WELCOME,
    _build_points_summary_text,
    _build_quick_report_request,
    _is_italian_pizza_system,
)


class BotQuickActionsTest(unittest.TestCase):
    def test_italian_pizza_system_detected_by_name(self):
        self.assertTrue(_is_italian_pizza_system({"system_name": "italian_pizza", "url": "https://example.com"}))

    def test_italian_pizza_system_detected_by_url(self):
        self.assertTrue(_is_italian_pizza_system({"system_name": "web-system", "url": "https://tochka.italianpizza.ru/login"}))

    def test_non_italian_pizza_system_not_detected(self):
        self.assertFalse(_is_italian_pizza_system({"system_name": "crm", "url": "https://portal.example.com"}))

    def test_quick_report_request_for_stoplist(self):
        request = _build_quick_report_request("stoplist", "Артемовский, Гагарина 2А")
        self.assertEqual(request, "Собери отчёт по стоп-листу для точки Артемовский, Гагарина 2А")

    def test_quick_report_request_for_blanks_12h(self):
        request = _build_quick_report_request("blanks_12h", "Артемовский, Гагарина 2А")
        self.assertIn("за последние 12 часов", request)

    def test_points_summary_marks_delivery_enabled_point(self):
        point = SimpleNamespace(id=3, display_name="Сухой Лог, Белинского 40", report_delivery_enabled=True)
        summary = _build_points_summary_text([point])
        self.assertIn("Сухой Лог, Белинского 40", summary)
        self.assertIn("— отчёты в чат", summary)

    def test_agent_welcome_no_longer_mentions_stats_or_profile(self):
        self.assertNotIn("Текущий профиль", AGENT_WELCOME)
        self.assertNotIn("статистика", AGENT_WELCOME.lower())

    def test_agent_welcome_prefers_free_text_instead_of_buttons(self):
        self.assertIn("просто пишете запрос", AGENT_WELCOME)
        self.assertNotIn("кнопкой", AGENT_WELCOME)

    def test_empty_points_summary_no_longer_pushes_button_only_flow(self):
        summary = _build_points_summary_text([])
        self.assertIn("обычным сообщением", summary)
        self.assertIn("пришли стоп-лист", summary)
        self.assertNotIn("в кнопках", summary)


if __name__ == "__main__":
    unittest.main()
