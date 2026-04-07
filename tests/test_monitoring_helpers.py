import unittest

from data_agent.monitoring import (
    build_monitor_saved_note,
    format_monitor_interval,
    scenario_to_monitor_type,
)


class MonitoringHelpersTest(unittest.TestCase):
    def test_scenario_to_monitor_type(self):
        self.assertEqual(scenario_to_monitor_type("blanks_report"), "blanks")
        self.assertEqual(scenario_to_monitor_type("stoplist_report"), "stoplist")
        self.assertIsNone(scenario_to_monitor_type("reviews_report"))

    def test_format_monitor_interval(self):
        self.assertEqual(format_monitor_interval(60), "каждый час")
        self.assertEqual(format_monitor_interval(180), "каждые 3 часа")
        self.assertEqual(format_monitor_interval(120), "каждые 2 ч.")

    def test_build_monitor_saved_note(self):
        text = build_monitor_saved_note(
            monitor_type="stoplist",
            point_name="Екатеринбург, Малышева 5",
            interval_minutes=60,
            chat_title="Команда Точки 1",
        )
        self.assertIn("Мониторинг сохранён", text)
        self.assertIn("стоп-лист", text)
        self.assertIn("каждый час", text)
        self.assertIn("Команда Точки 1", text)


if __name__ == "__main__":
    unittest.main()
