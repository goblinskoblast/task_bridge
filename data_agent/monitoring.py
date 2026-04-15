from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import TIMEZONE


MONITOR_SCENARIO_TO_TYPE = {
    "reviews_report": "reviews",
    "blanks_report": "blanks",
    "stoplist_report": "stoplist",
}

MONITOR_TYPE_LABELS = {
    "reviews": "отзывы",
    "blanks": "бланки",
    "stoplist": "стоп-лист",
}

MONITOR_USER_TIMEZONE = "Asia/Yekaterinburg"
MONITOR_USER_TIMEZONE_LABEL = "по Екатеринбургу"
DEFAULT_MONITOR_START_HOUR = 10
DEFAULT_MONITOR_END_HOUR = 22


def scenario_to_monitor_type(scenario: str) -> Optional[str]:
    return MONITOR_SCENARIO_TO_TYPE.get((scenario or "").strip())


def format_monitor_interval(minutes: int) -> str:
    if minutes == 60:
        return "каждый час"
    if minutes == 180:
        return "каждые 3 часа"
    if minutes == 1440:
        return "каждый день"
    hours = minutes / 60
    if hours.is_integer():
        whole_hours = int(hours)
        return f"каждые {whole_hours} ч."
    return f"каждые {minutes} мин."


def default_monitor_window_hours() -> tuple[int, int]:
    return DEFAULT_MONITOR_START_HOUR, DEFAULT_MONITOR_END_HOUR


def convert_monitor_window_hours(
    start_hour: int,
    end_hour: int,
    *,
    source_timezone: str,
    target_timezone: str,
) -> tuple[int, int]:
    source_tz = ZoneInfo(source_timezone)
    target_tz = ZoneInfo(target_timezone)
    reference = datetime(2026, 1, 15)
    start_at = reference.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=source_tz)
    end_at = reference.replace(hour=end_hour, minute=0, second=0, microsecond=0, tzinfo=source_tz)
    return start_at.astimezone(target_tz).hour, end_at.astimezone(target_tz).hour


def user_monitor_window_to_service_hours(start_hour: int, end_hour: int) -> tuple[int, int]:
    return convert_monitor_window_hours(
        start_hour,
        end_hour,
        source_timezone=MONITOR_USER_TIMEZONE,
        target_timezone=TIMEZONE,
    )


def service_monitor_window_to_user_hours(start_hour: int, end_hour: int) -> tuple[int, int]:
    return convert_monitor_window_hours(
        start_hour,
        end_hour,
        source_timezone=TIMEZONE,
        target_timezone=MONITOR_USER_TIMEZONE,
    )


def format_monitor_window(start_hour: int, end_hour: int, *, timezone_label: str = MONITOR_USER_TIMEZONE_LABEL) -> str:
    return f"с {start_hour:02d}:00 до {end_hour:02d}:00 {timezone_label}"


def build_monitor_saved_note(
    *,
    monitor_type: str,
    point_name: str,
    interval_minutes: int,
    chat_title: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    timezone_label: str = MONITOR_USER_TIMEZONE_LABEL,
) -> str:
    monitor_label = MONITOR_TYPE_LABELS.get(monitor_type, monitor_type)
    interval_label = format_monitor_interval(interval_minutes)
    window_label = ""
    if start_hour is not None and end_hour is not None:
        window_label = f", {format_monitor_window(start_hour, end_hour, timezone_label=timezone_label)}"
    suffix = f" Чат доставки: {chat_title}." if chat_title else ""

    if monitor_type == "blanks":
        return (
            f"Включил мониторинг {monitor_label} по точке {point_name}. "
            f"Проверка: {interval_label}{window_label}. "
            f"Если появятся красные бланки, сразу пришлю уведомление."
            f"{suffix}"
        )

    if monitor_type == "stoplist":
        return (
            f"Включил мониторинг {monitor_label} по точке {point_name}. "
            f"Проверка: {interval_label}{window_label}. "
            f"Буду присылать изменения и плановые обновления по стоп-листу."
            f"{suffix}"
        )

    if monitor_type == "reviews":
        return (
            f"Включил мониторинг {monitor_label}. "
            f"Проверка: {interval_label}{window_label}. "
            f"Буду присылать новые отчёты по отзывам."
            f"{suffix}"
        )

    return (
        f"Мониторинг сохранён: {monitor_label} по точке {point_name}. "
        f"Проверка: {interval_label}{window_label}."
        f"{suffix}"
    )
