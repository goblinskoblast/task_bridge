import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _build_user_safe_agent_answer
from data_agent.orchestrator import orchestrator


class UserFacingSafetyTest(unittest.TestCase):
    def test_failed_stoplist_hides_internal_public_point_error(self):
        result = {
            "status": "failed",
            "scenario": "stoplist_report",
            "answer": (
                "Стоп-лист не получен\n\n"
                "Не удалось определить публичную точку для стоп-листа: Сухой Лог, Белинского 40"
            ),
        }

        self.assertEqual(
            _build_user_safe_agent_answer(result),
            "Не удалось получить отчет по стоп-листу. Попробуйте позже.",
        )

    def test_failed_stoplist_hides_question_mark_mojibake(self):
        result = {
            "status": "failed",
            "scenario": "stoplist_report",
            "answer": (
                "????-???? ?? ??????????\n\n"
                "?????: ????? ???, ?????????? 40\n\n"
                "Не удалось определить публичную точку для стоп-листа: ????? ???, ?????????? 40"
            ),
        }

        self.assertEqual(
            _build_user_safe_agent_answer(result),
            "Не удалось получить отчет по стоп-листу. Попробуйте позже.",
        )

    def test_orchestrator_failed_stoplist_ignores_tool_message(self):
        answer = orchestrator._fallback_answer(
            {
                "stoplist_tool": {
                    "status": "failed",
                    "message": "Не удалось определить публичную точку для стоп-листа: Сухой Лог, Белинского 40",
                }
            }
        )

        self.assertEqual(answer, "Стоп-лист сейчас не удалось собрать. Попробуйте позже.")


if __name__ == "__main__":
    unittest.main()
