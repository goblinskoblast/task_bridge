from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from data_agent.monitor_scheduler import _is_monitor_due, _is_within_active_window, _monitor_blanks_period_hint


def test_monitor_active_window_includes_hours() -> None:
    config = SimpleNamespace(active_from_hour=10, active_to_hour=22)
    tz = ZoneInfo("Europe/Moscow")

    inside = datetime(2026, 4, 13, 10, 0, tzinfo=tz)
    assert _is_within_active_window(config, inside)

    inside_late = datetime(2026, 4, 13, 22, 30, tzinfo=tz)
    assert _is_within_active_window(config, inside_late)

    outside = datetime(2026, 4, 13, 9, 30, tzinfo=tz)
    assert not _is_within_active_window(config, outside)


def test_monitor_blanks_period_uses_interval_hours() -> None:
    config = SimpleNamespace(check_interval_minutes=180)
    assert _monitor_blanks_period_hint(config) == "за последние 3 часа"


def test_monitor_due_aligns_to_anchor_hour() -> None:
    config = SimpleNamespace(
        check_interval_minutes=180,
        active_from_hour=10,
        last_checked_at=None,
    )
    tz = ZoneInfo("Europe/Moscow")

    assert _is_monitor_due(config, datetime(2026, 4, 13, 10, 0, tzinfo=tz))
    assert not _is_monitor_due(config, datetime(2026, 4, 13, 11, 0, tzinfo=tz))
    assert _is_monitor_due(config, datetime(2026, 4, 13, 13, 0, tzinfo=tz))
