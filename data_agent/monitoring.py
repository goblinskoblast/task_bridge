from __future__ import annotations

from typing import Optional


MONITOR_SCENARIO_TO_TYPE = {
    "blanks_report": "blanks",
    "stoplist_report": "stoplist",
}

MONITOR_TYPE_LABELS = {
    "blanks": "бланки",
    "stoplist": "стоп-лист",
}


def scenario_to_monitor_type(scenario: str) -> Optional[str]:
    return MONITOR_SCENARIO_TO_TYPE.get((scenario or "").strip())


def format_monitor_interval(minutes: int) -> str:
    if minutes == 60:
        return "каждый час"
    if minutes == 180:
        return "каждые 3 часа"
    hours = minutes / 60
    if hours.is_integer():
        whole_hours = int(hours)
        return f"каждые {whole_hours} ч."
    return f"каждые {minutes} мин."


def build_monitor_saved_note(
    *,
    monitor_type: str,
    point_name: str,
    interval_minutes: int,
    chat_title: str | None = None,
) -> str:
    monitor_label = MONITOR_TYPE_LABELS.get(monitor_type, monitor_type)
    interval_label = format_monitor_interval(interval_minutes)
    suffix = f" Доставка: {chat_title}." if chat_title else ""
    return (
        f"\n\nМониторинг сохранён: {monitor_label} по точке {point_name}, {interval_label}."
        f"{suffix}"
    )
