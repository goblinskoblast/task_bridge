import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.review_report import ReviewReportService


class ReviewReportCriticalFocusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ReviewReportService()

    def test_summary_prioritizes_critical_reviews(self):
        rows = [
            {
                "branch": "Артёмовский, Гагарина 2а",
                "review": "Очень долго ждали доставку, пицца приехала холодная.",
                "rating": "2",
                "date": "2026-04-07 12:00:00",
            },
            {
                "branch": "Артёмовский, Гагарина 2а",
                "review": "Все понравилось, спасибо.",
                "rating": "5",
                "date": "2026-04-07 13:00:00",
            },
        ]

        summary = self.service._build_summary(
            rows,
            self.service._resolve_window("отзывы за неделю"),
            "https://example.com/reviews.csv",
            point_name="Артёмовский, Гагарина 2а",
            matched_branches=["Артёмовский, Гагарина 2а"],
        )

        self.assertEqual(summary["critical_reviews_count"], 1)
        self.assertIn("Критических отзывов (<4 звезды): 1", summary["report_text"])
        self.assertIn("Основные проблемы", summary["report_text"])
        self.assertNotIn("Основные похвалы", summary["report_text"])

    def test_summary_reports_absence_of_critical_reviews(self):
        rows = [
            {
                "branch": "Артёмовский, Гагарина 2а",
                "review": "Все отлично, очень вкусно.",
                "rating": "5",
                "date": "2026-04-07 13:00:00",
            }
        ]

        summary = self.service._build_summary(
            rows,
            self.service._resolve_window("отзывы за неделю"),
            "https://example.com/reviews.csv",
            point_name="Артёмовский, Гагарина 2а",
            matched_branches=["Артёмовский, Гагарина 2а"],
        )

        self.assertEqual(summary["critical_reviews_count"], 0)
        self.assertIn("Критических отзывов с оценкой ниже 4 звёзд", summary["report_text"])


if __name__ == "__main__":
    unittest.main()
