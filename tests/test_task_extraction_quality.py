import asyncio
import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.ai_extractor import _build_fallback_task, _looks_like_notification_email, analyze_message


class TaskExtractionQualityTest(unittest.TestCase):
    def test_acknowledgement_message_is_not_treated_as_task(self):
        result = asyncio.run(analyze_message("Ок, спасибо", use_ai=False))

        self.assertFalse(result["has_task"])

    def test_explicit_telegram_request_still_creates_task(self):
        result = asyncio.run(analyze_message("Проверь сайт и пришли отчет до 18:00", use_ai=False))

        self.assertTrue(result["has_task"])
        self.assertEqual(result["task"]["title"], "Проверить сайт и пришли отчет")

    def test_password_reset_email_is_filtered_as_notification(self):
        self.assertTrue(
            _looks_like_notification_email(
                subject="Password reset",
                body_text="Use this one-time password to reset your password.",
                from_address="security@example.com",
                email_headers={"From": "Security <security@example.com>"},
            )
        )

    def test_delivery_update_email_is_filtered_as_notification(self):
        self.assertTrue(
            _looks_like_notification_email(
                subject="Заказ в пути",
                body_text="Трек-номер 12345. Out for delivery.",
                from_address="noreply@delivery.example",
                email_headers={"From": "Delivery <noreply@delivery.example>"},
            )
        )

    def test_meeting_invite_email_is_kept_as_task(self):
        result = _build_fallback_task(
            source="email",
            current_text="",
            subject="Созвон по запуску",
            body_text="Подключись к созвону завтра в 15:00. Ссылка: https://meet.google.com/demo-room",
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["has_task"])


if __name__ == "__main__":
    unittest.main()
