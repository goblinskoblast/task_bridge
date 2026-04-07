import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.ai_extractor import _localize_task_to_russian_if_needed, _task_needs_russian_localization


class EmailTaskLocalizationTest(unittest.TestCase):
    def test_task_needs_russian_localization_for_english_task(self):
        self.assertTrue(
            _task_needs_russian_localization(
                {
                    "title": "Send link",
                    "description": "Please send the link as I do not have it in the email.",
                }
            )
        )

    def test_task_needs_russian_localization_skips_russian_task(self):
        self.assertFalse(
            _task_needs_russian_localization(
                {
                    "title": "Отправить ссылку",
                    "description": "Пожалуйста, пришлите ссылку, потому что ее нет в письме.",
                }
            )
        )

    def test_localize_task_to_russian_if_needed_updates_task_fields(self):
        provider = AsyncMock()
        provider.analyze_message = AsyncMock(
            return_value={
                "title": "Отправить ссылку",
                "description": "Пожалуйста, пришлите ссылку, потому что ее нет в письме.",
            }
        )

        result = {
            "has_task": True,
            "task": {
                "title": "Send link",
                "description": "Please send the link as I don't have it in the email.",
            },
        }

        with patch("bot.ai_extractor.get_ai_provider", return_value=provider):
            localized = __import__("asyncio").run(
                _localize_task_to_russian_if_needed(result, source="email")
            )

        self.assertEqual(localized["task"]["title"], "Отправить ссылку")
        self.assertIn("Пожалуйста, пришлите ссылку", localized["task"]["description"])


if __name__ == "__main__":
    unittest.main()
