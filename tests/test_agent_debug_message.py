import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _format_agent_debug_message


class AgentDebugMessageTest(unittest.TestCase):
    def test_format_agent_debug_message_contains_summary_and_request(self):
        text = _format_agent_debug_message(
            {
                "summary": "Trace: abc\nСценарий: blanks_report\nСтатус: failed",
                "user_message": "пришли бланки по точке",
                "answer": "Не удалось собрать бланки.",
            }
        )
        self.assertIn("Последняя диагностика агента", text)
        self.assertIn("Trace: abc", text)
        self.assertIn("Последний запрос: пришли бланки по точке", text)
        self.assertIn("Последний ответ: Не удалось собрать бланки.", text)


if __name__ == "__main__":
    unittest.main()
