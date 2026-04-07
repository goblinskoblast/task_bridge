import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.ai_extractor import _build_fallback_task, telegram_message_requires_context


class TelegramExtractionGuardrailsTest(unittest.TestCase):
    def test_self_contained_message_does_not_need_context(self):
        self.assertFalse(telegram_message_requires_context("Сделай презентацию до пятницы"))

    def test_reference_message_requests_context(self):
        self.assertTrue(telegram_message_requires_context("Это сделай до пятницы"))

    def test_fallback_does_not_copy_context_into_description(self):
        result = _build_fallback_task(
            source="telegram",
            current_text="Пришли отчет клиенту",
            context_messages=[
                {"text": "По проекту Альфа до субботы"},
            ],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["task"]["description"], "Пришли отчет клиенту")
        self.assertNotIn("Контекст:", result["task"]["description"])

    def test_fallback_rejects_context_only_addendum(self):
        result = _build_fallback_task(
            source="telegram",
            current_text="И еще к субботе",
            context_messages=[
                {"text": "Подготовь архитектуру проекта"},
            ],
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
