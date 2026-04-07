import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.ai_extractor import _looks_like_notification_email


class EmailNoiseFiltersTest(unittest.TestCase):
    def test_bulk_newsletter_headers_are_filtered_out(self):
        self.assertTrue(
            _looks_like_notification_email(
                subject="Скидки недели",
                body_text="Большая распродажа. Отписаться можно внизу письма.",
                from_address="news@shop.example",
                email_headers={
                    "List-Unsubscribe": "<mailto:unsubscribe@example>",
                    "Precedence": "bulk",
                    "From": "Shop Newsletter <news@shop.example>",
                },
            )
        )

    def test_spam_headers_are_filtered_out(self):
        self.assertTrue(
            _looks_like_notification_email(
                subject="Promo",
                body_text="Акция только сегодня",
                from_address="promo@example.com",
                email_headers={
                    "X-Spam-Flag": "YES",
                    "X-Spam-Status": "Yes, score=7.1",
                    "IMAP-Flags": ["$Junk"],
                },
            )
        )

    def test_strong_task_request_survives_automated_sender(self):
        self.assertFalse(
            _looks_like_notification_email(
                subject="Нужно отправить акт сегодня",
                body_text="Пожалуйста, отправьте подписанный акт до 18:00.",
                from_address="noreply@vendor.example",
                email_headers={
                    "Auto-Submitted": "auto-generated",
                    "From": "Vendor Robot <noreply@vendor.example>",
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
