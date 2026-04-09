import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import AGENT_WELCOME, _build_points_summary_text, _build_quick_report_request


class BotQuickActionsTest(unittest.TestCase):
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
        self.assertIn("• в чат", summary)

    def test_agent_welcome_no_longer_mentions_stats_or_profile(self):
        self.assertNotIn("Текущий профиль", AGENT_WELCOME)
        self.assertNotIn("статистика", AGENT_WELCOME.lower())


if __name__ == "__main__":
    unittest.main()
