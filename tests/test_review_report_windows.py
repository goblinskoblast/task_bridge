import os
import unittest
from datetime import timedelta

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.review_report import ReviewReportService


class ReviewReportWindowsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ReviewReportService()

    def test_resolve_today_window(self):
        window = self.service._resolve_window("отзывы за сегодня")
        self.assertEqual(window.label, "за сегодня")
        self.assertEqual(window.end - window.start, timedelta(days=1))

    def test_resolve_yesterday_window(self):
        window = self.service._resolve_window("отзывы за вчера")
        self.assertEqual(window.label, "за вчера")
        self.assertEqual(window.end - window.start, timedelta(days=1))

    def test_resolve_last_12_hours_window(self):
        window = self.service._resolve_window("отзывы за последние 12 часов")
        self.assertEqual(window.label, "за последние 12 часов")
        self.assertEqual(window.end - window.start, timedelta(hours=12))

    def test_resolve_last_7_days_window(self):
        window = self.service._resolve_window("отзывы за последние 7 дней")
        self.assertEqual(window.label, "за последние 7 дней")
        self.assertEqual(window.end - window.start, timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
