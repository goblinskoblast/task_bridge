import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.orchestrator import orchestrator


class OrchestratorReviewFallbackTest(unittest.TestCase):
    def test_review_unavailable_message_is_neutral(self):
        result = orchestrator._fallback_answer(
            {
                "review_tool": {
                    "status": "not_configured",
                    "message": "Отчёт по отзывам для точки Верхний Уфалей, Ленина 147 за неделю пока недоступен.",
                }
            }
        )

        self.assertEqual(
            result,
            "Отчёт по отзывам для точки Верхний Уфалей, Ленина 147 за неделю пока недоступен.",
        )
        self.assertNotIn("Причина:", result)


if __name__ == "__main__":
    unittest.main()
