import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _build_profile_summary, _build_quick_report_request
from bot.handlers import _build_welcome_message


class BotQuickActionsTest(unittest.TestCase):
    def test_quick_report_request_for_stoplist(self):
        request = _build_quick_report_request("stoplist", "Артемовский, Гагарина 2А")
        self.assertEqual(request, "Собери отчёт по стоп-листу для точки Артемовский, Гагарина 2А")

    def test_quick_report_request_for_blanks_12h(self):
        request = _build_quick_report_request("blanks_12h", "Артемовский, Гагарина 2А")
        self.assertIn("за последние 12 часов", request)

    def test_profile_summary_skips_empty_fields(self):
        profile = type(
            "Profile",
            (),
            {
                "business_context": "сеть пиццерий",
                "primary_goal": "",
                "reporting_frequency": "ежедневно",
                "default_report_chat_title": None,
            },
        )()
        summary = _build_profile_summary(profile)
        self.assertIn("Контекст: сеть пиццерий", summary)
        self.assertIn("Ритм: ежедневно", summary)
        self.assertNotIn("Фокус:", summary)

    def test_welcome_message_mentions_active_tasks(self):
        text = _build_welcome_message(is_first_auth=False, pending_count=3)
        self.assertIn("3", text)
        self.assertIn("активных задач", text)


if __name__ == "__main__":
    unittest.main()
