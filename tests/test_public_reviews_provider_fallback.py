import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.scenario_engine import _run_public_reviews_browser


class PublicReviewsProviderFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_access_denied_provider_is_excluded_from_user_report(self):
        with patch(
            "data_agent.scenario_engine.browser_agent.extract_data",
            AsyncMock(side_effect=["yandex report", "ОШИБКА_ДОСТУПА: 2GIS временно отклонил автоматический запрос"]),
        ):
            result = await _run_public_reviews_browser(
                "собери отзывы по Артёмовский, Гагарина 2а за неделю",
                targets=["Артёмовский, Гагарина 2а"],
            )

        self.assertEqual(result["status"], "ok")
        self.assertIn("Яндекс Карты", result["report_text"])
        self.assertIn("yandex report", result["report_text"])
        self.assertNotIn("2GIS:\nОШИБКА_ДОСТУПА", result["report_text"])
        self.assertEqual(len(result["failed_providers"]), 1)
        self.assertEqual(result["failed_providers"][0]["provider"], "2gis")


if __name__ == "__main__":
    unittest.main()
