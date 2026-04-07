import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.review_report import ReviewReportService


class ReviewMonitoringSupportTest(unittest.TestCase):
    def test_build_report_for_window_label_uses_regular_parser(self):
        service = ReviewReportService()
        window = service._resolve_window("отзывы за последние 7 дней")
        self.assertEqual(window.label, "за последние 7 дней")


if __name__ == "__main__":
    unittest.main()
