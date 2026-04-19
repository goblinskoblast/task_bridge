import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import (
    _clear_profile_report_chat,
    _get_profile_report_chat,
    _resolve_report_category_from_action,
    _resolve_report_category_from_result,
    _set_profile_report_chat,
)
from db.models import DataAgentProfile


class ReportChatPreferencesTest(unittest.TestCase):
    def test_profile_report_chat_falls_back_to_legacy_default(self):
        profile = DataAgentProfile(
            default_report_chat_id=-100123,
            default_report_chat_title="Общий чат",
        )

        chat_id, chat_title = _get_profile_report_chat(profile, "stoplist")

        self.assertEqual(chat_id, -100123)
        self.assertEqual(chat_title, "Общий чат")

    def test_profile_report_chat_uses_category_specific_target(self):
        profile = DataAgentProfile(
            default_report_chat_id=-100123,
            default_report_chat_title="Общий чат",
        )
        chat = SimpleNamespace(chat_id=-100456, title="Стопы", username=None)

        _set_profile_report_chat(profile, "stoplist", chat)
        chat_id, chat_title = _get_profile_report_chat(profile, "stoplist")

        self.assertEqual(chat_id, -100456)
        self.assertEqual(chat_title, "Стопы")

        _clear_profile_report_chat(profile, "stoplist")
        fallback_id, fallback_title = _get_profile_report_chat(profile, "stoplist")
        self.assertEqual(fallback_id, -100123)
        self.assertEqual(fallback_title, "Общий чат")

    def test_profile_report_chat_hides_corrupted_title(self):
        profile = DataAgentProfile(
            default_report_chat_id=-100123,
            default_report_chat_title="????????",
        )

        chat_id, chat_title = _get_profile_report_chat(profile, "stoplist")

        self.assertEqual(chat_id, -100123)
        self.assertEqual(chat_title, "привязанный чат")

    def test_report_category_resolution(self):
        self.assertEqual(_resolve_report_category_from_action("stoplist"), "stoplist")
        self.assertEqual(_resolve_report_category_from_action("blanks_current"), "blanks")
        self.assertEqual(_resolve_report_category_from_action("reviews_week"), "reviews")
        self.assertIsNone(_resolve_report_category_from_action("unknown"))

        self.assertEqual(_resolve_report_category_from_result({"scenario": "stoplist_report"}), "stoplist")
        self.assertEqual(_resolve_report_category_from_result({"scenario": "blanks_report"}), "blanks")
        self.assertEqual(_resolve_report_category_from_result({"scenario": "reviews_report"}), "reviews")
        self.assertIsNone(_resolve_report_category_from_result({"scenario": "other"}))


if __name__ == "__main__":
    unittest.main()
