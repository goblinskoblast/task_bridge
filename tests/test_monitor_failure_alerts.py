import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from db.models import DataAgentMonitorConfig
from data_agent.monitor_scheduler import _build_monitor_failure_hash, _build_monitor_failure_message


class MonitorFailureAlertsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = DataAgentMonitorConfig(
            id=12,
            user_id=7,
            monitor_type="blanks",
            point_name="Екатеринбург, Малышева 5",
            check_interval_minutes=60,
        )

    def test_build_monitor_failure_hash_is_stable(self):
        result = {
            "status": "failed",
            "message": "Login failed",
            "diagnostics": {"stage": "login_submit"},
        }
        first = _build_monitor_failure_hash(self.config, result)
        second = _build_monitor_failure_hash(self.config, result)
        self.assertEqual(first, second)

    def test_build_monitor_failure_message_contains_type_and_point(self):
        message = _build_monitor_failure_message(
            self.config,
            "Trace: monitor-12\nСценарий: blanks_monitor\nСтатус: failed",
        )
        self.assertIn("Мониторинг завершился с ошибкой", message)
        self.assertIn("Тип: blanks", message)
        self.assertIn("Точка: Екатеринбург, Малышева 5", message)


if __name__ == "__main__":
    unittest.main()
