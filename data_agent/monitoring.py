from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from config import TIMEZONE


REPORT_CHAT_FALLBACK_LABEL = "привязанный чат"
_USER_TEXT_MOJIBAKE_MARKERS = (
    "????",
    "Р С",
    "РЎ",
    "СЃ",
    "С‚",
    "Ð",
    "Ñ",
)


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


def looks_corrupted_user_text(text: str | None) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(marker in normalized for marker in _USER_TEXT_MOJIBAKE_MARKERS):
        return True
    question_marks = normalized.count("?")
    letters = sum(1 for char in normalized if char.isalpha())
    return question_marks >= 4 and question_marks >= max(letters // 2, 4)


def resolve_user_facing_chat_title(chat_title: str | None) -> str | None:
    normalized = (chat_title or "").strip()
    if not normalized:
        return None
    if looks_corrupted_user_text(normalized):
        return None
    return normalized


def format_user_facing_chat_label(chat_title: str | None) -> str:
    resolved_title = resolve_user_facing_chat_title(chat_title)
    if resolved_title:
        return f"чат «{resolved_title}»"
    return REPORT_CHAT_FALLBACK_LABEL


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


def format_monitor_moment(value: datetime | None, *, timezone_name: str = MONITOR_USER_TIMEZONE) -> str:
    if value is None:
        return "ещё не было"

    target_tz = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        localized = value.replace(tzinfo=timezone.utc).astimezone(target_tz)
    else:
        localized = value.astimezone(target_tz)

    now = datetime.now(target_tz)
    if localized.date() == now.date():
        return localized.strftime("сегодня в %H:%M")
    if localized.date() == (now.date() - timedelta(days=1)):
        return localized.strftime("вчера в %H:%M")
    if localized.date() == (now.date() + timedelta(days=1)):
        return localized.strftime("\u0437\u0430\u0432\u0442\u0440\u0430 \u0432 %H:%M")
    if localized.year == now.year:
        return localized.strftime("%d.%m в %H:%M")
    return localized.strftime("%d.%m.%Y в %H:%M")


def _normalize_monitor_reference_time(value: datetime | None, *, timezone_name: str) -> datetime:
    target_tz = ZoneInfo(timezone_name)
    if value is None:
        return datetime.now(target_tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(target_tz)
    return value.astimezone(target_tz)


def _is_hour_within_window(hour: int, start_hour: int | None, end_hour: int | None) -> bool:
    if start_hour is None or end_hour is None:
        return True
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour <= end_hour
    return hour >= start_hour or hour <= end_hour


def get_next_monitor_check_at(
    *,
    check_interval_minutes: int,
    active_from_hour: int | None = None,
    active_to_hour: int | None = None,
    last_checked_at: datetime | None = None,
    now: datetime | None = None,
    service_timezone_name: str = TIMEZONE,
    user_timezone_name: str = MONITOR_USER_TIMEZONE,
) -> datetime | None:
    interval_minutes = int(check_interval_minutes or 0)
    if interval_minutes <= 0 or interval_minutes % 60 != 0:
        return None

    service_now = _normalize_monitor_reference_time(now, timezone_name=service_timezone_name)
    last_checked_service: datetime | None = None
    if last_checked_at is not None:
        last_checked_service = _normalize_monitor_reference_time(
            last_checked_at,
            timezone_name=service_timezone_name,
        )

    interval_hours = max(1, interval_minutes // 60)
    anchor_hour = active_from_hour if active_from_hour is not None else 0
    candidate = service_now.replace(minute=0, second=0, microsecond=0)
    if service_now.minute != 0 or service_now.second != 0 or service_now.microsecond != 0:
        candidate += timedelta(hours=1)

    for _ in range(24 * 8):
        if _is_hour_within_window(candidate.hour, active_from_hour, active_to_hour):
            if (candidate.hour - anchor_hour) % interval_hours == 0:
                if last_checked_service is None or not (
                    last_checked_service.date() == candidate.date()
                    and last_checked_service.hour == candidate.hour
                ):
                    return candidate.astimezone(ZoneInfo(user_timezone_name))
        candidate += timedelta(hours=1)

    return None


def format_monitor_next_check(
    *,
    check_interval_minutes: int,
    active_from_hour: int | None = None,
    active_to_hour: int | None = None,
    last_checked_at: datetime | None = None,
    now: datetime | None = None,
    service_timezone_name: str = TIMEZONE,
    user_timezone_name: str = MONITOR_USER_TIMEZONE,
) -> str:
    next_check_at = get_next_monitor_check_at(
        check_interval_minutes=check_interval_minutes,
        active_from_hour=active_from_hour,
        active_to_hour=active_to_hour,
        last_checked_at=last_checked_at,
        now=now,
        service_timezone_name=service_timezone_name,
        user_timezone_name=user_timezone_name,
    )
    if next_check_at is None:
        return "\u0432 \u0431\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0439 \u0446\u0438\u043a\u043b"
    return format_monitor_moment(next_check_at, timezone_name=user_timezone_name)


def build_monitor_saved_note(
    *,
    monitor_type: str,
    point_name: str,
    interval_minutes: int,
    chat_title: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    timezone_label: str = MONITOR_USER_TIMEZONE_LABEL,
    action: str = "enabled",
) -> str:
    monitor_label = MONITOR_TYPE_LABELS.get(monitor_type, monitor_type)
    lead_labels = {
        "blanks": "бланков",
        "stoplist": "стоп-листа",
        "reviews": "отзывов",
    }
    lead_monitor_label = lead_labels.get(monitor_type, monitor_label)
    interval_label = format_monitor_interval(interval_minutes)
    window_label = ""
    if start_hour is not None and end_hour is not None:
        window_label = f", {format_monitor_window(start_hour, end_hour, timezone_label=timezone_label)}"
    resolved_chat_title = resolve_user_facing_chat_title(chat_title)
    suffix = f" Чат доставки: {resolved_chat_title or REPORT_CHAT_FALLBACK_LABEL}." if chat_title else ""
    if action == "updated":
        lead_with_point = f"Обновил мониторинг {lead_monitor_label} по точке {point_name}. "
        lead_reviews = f"Обновил мониторинг {lead_monitor_label}. "
    elif action == "already_configured":
        lead_with_point = f"Мониторинг {lead_monitor_label} по точке {point_name} уже настроен. "
        lead_reviews = f"Мониторинг {lead_monitor_label} уже настроен. "
    else:
        lead_with_point = f"Включил мониторинг {lead_monitor_label} по точке {point_name}. "
        lead_reviews = f"Включил мониторинг {lead_monitor_label}. "

    if monitor_type == "blanks":
        return (
            f"{lead_with_point}"
            f"Проверка: {interval_label}{window_label}. "
            f"Если появятся красные бланки, сразу пришлю уведомление."
            f"{suffix}"
        )

    if monitor_type == "stoplist":
        return (
            f"{lead_with_point}"
            f"Проверка: {interval_label}{window_label}. "
            f"Буду присылать изменения и плановые обновления по стоп-листу."
            f"{suffix}"
        )

    if monitor_type == "reviews":
        return (
            f"{lead_reviews}"
            f"Проверка: {interval_label}{window_label}. "
            f"Буду присылать новые отчёты по отзывам."
            f"{suffix}"
        )

    return (
        f"Мониторинг сохранён: {monitor_label} по точке {point_name}. "
        f"Проверка: {interval_label}{window_label}."
        f"{suffix}"
    )


def build_monitor_disabled_note(*, monitor_type: str, point_name: str) -> str:
    labels = {
        "blanks": "бланков",
        "stoplist": "стоп-листа",
        "reviews": "отзывов",
    }
    monitor_label = labels.get(monitor_type, MONITOR_TYPE_LABELS.get(monitor_type, monitor_type))
    return f"Отключил мониторинг {monitor_label} по точке {point_name}."


def build_monitor_not_found_note(*, monitor_type: str, point_name: str) -> str:
    labels = {
        "blanks": "бланков",
        "stoplist": "стоп-листа",
        "reviews": "отзывов",
    }
    monitor_label = labels.get(monitor_type, MONITOR_TYPE_LABELS.get(monitor_type, monitor_type))
    return f"Активный мониторинг {monitor_label} по точке {point_name} сейчас не найден."
