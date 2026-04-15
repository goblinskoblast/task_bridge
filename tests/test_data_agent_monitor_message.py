import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent.service import DataAgentService


class DataAgentMonitorMessageTest(unittest.TestCase):
    def test_merge_answer_with_monitor_note_puts_confirmation_first(self):
        merged = DataAgentService._merge_answer_with_monitor_note(
            "Текущий отчёт по точке готов.",
            "Включил мониторинг бланков по точке Сухой Лог, Белинского 40.",
        )

        self.assertTrue(merged.startswith("Включил мониторинг"))
        self.assertIn("Текущий отчёт по точке готов.", merged)

    def test_merge_answer_with_monitor_note_handles_empty_answer(self):
        merged = DataAgentService._merge_answer_with_monitor_note(
            "",
            "Включил мониторинг стоп-листа по точке Сухой Лог, Белинского 40.",
        )

        self.assertEqual(
            merged,
            "Включил мониторинг стоп-листа по точке Сухой Лог, Белинского 40.",
        )


if __name__ == "__main__":
    unittest.main()
