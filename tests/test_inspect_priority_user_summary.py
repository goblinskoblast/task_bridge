import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from scripts.inspect_priority_user_summary import _build_executive_summary, _monitor_state


class InspectPriorityUserSummaryTest(unittest.TestCase):
    def test_monitor_state_prefers_live_red_blanks_alert(self):
        item = SimpleNamespace(
            monitor_type="blanks",
            last_status="ok",
            last_result_json={"has_red_flags": True},
        )

        self.assertEqual(_monitor_state(item), "alert")

    def test_monitor_state_marks_retry_statuses(self):
        item = SimpleNamespace(
            monitor_type="stoplist",
            last_status="needs_period",
            last_result_json={},
        )

        self.assertEqual(_monitor_state(item), "retry")

    def test_build_executive_summary_mentions_current_alert_and_telegram_limits(self):
        active_configs = [
            SimpleNamespace(
                monitor_type="blanks",
                point_name="Реж, Ленина 17",
                last_status="ok",
                last_result_json={"has_red_flags": True},
            ),
            SimpleNamespace(
                monitor_type="stoplist",
                point_name="Сухой Лог, Белинского 40",
                last_status="ok",
                last_result_json={},
            ),
        ]
        events = [
            SimpleNamespace(monitor_type="blanks", severity="critical", sent_to_telegram=True),
            SimpleNamespace(monitor_type="stoplist", severity="info", sent_to_telegram=True),
        ]
        summary = _build_executive_summary(
            since_hours=48,
            active_configs=active_configs,
            events=events,
            linked_events=[object()],
            requests=[],
            visible_messages=[],
            visible_forwarded=[],
            user_support_messages=[],
            attention_matches=[],
        )

        joined = "\n".join(summary)
        self.assertIn("За последние 48 ч", joined)
        self.assertIn("Текущая красная зона: Реж, Ленина 17.", joined)
        self.assertIn("Telegram Bot API не показывает точное прочтение", joined)


if __name__ == "__main__":
    unittest.main()
