import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_handlers import _build_points_summary_text


class SavedPointsDisplayTest(unittest.TestCase):
    def test_points_summary_uses_user_facing_sequence_instead_of_db_ids(self):
        points = [
            SimpleNamespace(id=7, display_name="Верхний Уфалей, Ленина 147", report_delivery_enabled=False),
            SimpleNamespace(id=42, display_name="Сухой Лог, Белинского 40", report_delivery_enabled=True),
        ]

        summary = _build_points_summary_text(points)

        self.assertIn("• <b>1.</b> Верхний Уфалей, Ленина 147", summary)
        self.assertIn("• <b>2.</b> Сухой Лог, Белинского 40 — отчёты в чат", summary)
        self.assertNotIn("#7", summary)
        self.assertNotIn("#42", summary)


if __name__ == "__main__":
    unittest.main()
