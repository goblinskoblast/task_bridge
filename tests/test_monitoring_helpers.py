import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from data_agent.monitoring import (
    build_monitor_saved_note,
    default_monitor_window_hours,
    format_monitor_interval,
    format_monitor_next_check,
    format_monitor_window,
    get_next_monitor_check_at,
    scenario_to_monitor_type,
    service_monitor_window_to_user_hours,
    user_monitor_window_to_service_hours,
)


class MonitoringHelpersTest(unittest.TestCase):
    def test_scenario_to_monitor_type(self):
        self.assertEqual(scenario_to_monitor_type("blanks_report"), "blanks")
        self.assertEqual(scenario_to_monitor_type("stoplist_report"), "stoplist")
        self.assertEqual(scenario_to_monitor_type("reviews_report"), "reviews")

    def test_format_monitor_interval(self):
        self.assertEqual(format_monitor_interval(60), "каждый час")
        self.assertEqual(format_monitor_interval(180), "каждые 3 часа")
        self.assertEqual(format_monitor_interval(1440), "каждый день")
        self.assertEqual(format_monitor_interval(120), "каждые 2 ч.")

    def test_build_monitor_saved_note(self):
        text = build_monitor_saved_note(
            monitor_type="stoplist",
            point_name="Екатеринбург, Малышева 5",
            interval_minutes=60,
            chat_title="Команда Точки 1",
            start_hour=10,
            end_hour=22,
        )
        self.assertIn("Включил мониторинг", text)
        self.assertIn("стоп-лист", text)
        self.assertIn("Проверка: каждый час", text)
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", text)
        self.assertIn("Команда Точки 1", text)

    def test_build_monitor_saved_note_for_blanks_explains_red_alert_behavior(self):
        text = build_monitor_saved_note(
            monitor_type="blanks",
            point_name="Сухой Лог, Белинского 40",
            interval_minutes=180,
            start_hour=10,
            end_hour=22,
        )
        self.assertIn("Включил мониторинг бланков", text)
        self.assertIn("каждые 3 часа", text)
        self.assertIn("Если появятся красные бланки, сразу пришлю уведомление.", text)

    def test_build_monitor_saved_note_supports_update_action(self):
        text = build_monitor_saved_note(
            monitor_type="blanks",
            point_name="Сухой Лог, Белинского 40",
            interval_minutes=120,
            start_hour=11,
            end_hour=21,
            action="updated",
        )
        self.assertIn("Обновил мониторинг бланков", text)
        self.assertIn("каждые 2 ч.", text)

    def test_default_monitor_window_hours(self):
        self.assertEqual(default_monitor_window_hours(), (10, 22))

    def test_user_monitor_window_to_service_hours(self):
        self.assertEqual(user_monitor_window_to_service_hours(10, 22), (8, 20))

    def test_service_monitor_window_to_user_hours(self):
        self.assertEqual(service_monitor_window_to_user_hours(8, 20), (10, 22))

    def test_format_monitor_window(self):
        self.assertEqual(format_monitor_window(10, 22), "с 10:00 до 22:00 по Екатеринбургу")


    def test_get_next_monitor_check_at_uses_user_timezone(self):
        next_at = get_next_monitor_check_at(
            check_interval_minutes=180,
            active_from_hour=8,
            active_to_hour=20,
            now=datetime(2026, 4, 15, 14, 17, tzinfo=ZoneInfo("Europe/Moscow")),
        )
        self.assertEqual(next_at.strftime("%Y-%m-%d %H:%M"), "2026-04-15 19:00")
        self.assertEqual(next_at.tzinfo, ZoneInfo("Asia/Yekaterinburg"))

    def test_get_next_monitor_check_at_rolls_to_next_day_after_window(self):
        next_at = get_next_monitor_check_at(
            check_interval_minutes=180,
            active_from_hour=8,
            active_to_hour=20,
            now=datetime(2026, 4, 15, 20, 30, tzinfo=ZoneInfo("Europe/Moscow")),
        )
        self.assertEqual(next_at.strftime("%Y-%m-%d %H:%M"), "2026-04-16 10:00")

    def test_get_next_monitor_check_at_skips_current_slot_when_it_was_already_checked(self):
        next_at = get_next_monitor_check_at(
            check_interval_minutes=180,
            active_from_hour=8,
            active_to_hour=20,
            last_checked_at=datetime(2026, 4, 15, 17, 0, tzinfo=ZoneInfo("Europe/Moscow")),
            now=datetime(2026, 4, 15, 17, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        )
        self.assertEqual(next_at.strftime("%Y-%m-%d %H:%M"), "2026-04-15 22:00")

    def test_format_monitor_next_check_falls_back_to_generic_label_for_non_hourly_interval(self):
        label = format_monitor_next_check(
            check_interval_minutes=90,
            active_from_hour=8,
            active_to_hour=20,
            now=datetime(2026, 4, 15, 14, 17, tzinfo=ZoneInfo("Europe/Moscow")),
        )
        self.assertEqual(label, "\u0432 \u0431\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0439 \u0446\u0438\u043a\u043b")


if __name__ == "__main__":
    unittest.main()
