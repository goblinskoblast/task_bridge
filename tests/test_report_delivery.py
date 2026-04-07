import unittest

from bot.report_delivery import (
    build_report_delivery_message,
    is_report_delivery_candidate,
    trim_telegram_text,
)


class ReportDeliveryTest(unittest.TestCase):
    def test_completed_report_scenario_is_delivery_candidate(self):
        self.assertTrue(
            is_report_delivery_candidate(
                {
                    "status": "completed",
                    "scenario": "reviews_report",
                    "answer": "Отчет готов",
                }
            )
        )

    def test_non_completed_response_is_not_delivery_candidate(self):
        self.assertFalse(
            is_report_delivery_candidate(
                {
                    "status": "awaiting_user_input",
                    "scenario": "reviews_report",
                    "answer": "Уточните точку",
                }
            )
        )

    def test_trim_telegram_text_adds_ellipsis(self):
        trimmed = trim_telegram_text("x" * 5000, limit=32)
        self.assertEqual(len(trimmed), 32)
        self.assertTrue(trimmed.endswith("…"))

    def test_build_report_delivery_message_contains_context(self):
        text = build_report_delivery_message(
            requester_name="@owner",
            user_message="пришли стоп-лист",
            answer="Стоп-лист пуст",
        )
        self.assertIn("Запросил: @owner", text)
        self.assertIn("Запрос: пришли стоп-лист", text)
        self.assertIn("Стоп-лист пуст", text)


if __name__ == "__main__":
    unittest.main()
