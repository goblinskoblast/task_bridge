from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from db.models import StopListIncident

from .stoplist_reactions import format_manager_status_label


@dataclass(frozen=True)
class StopListMonitorCard:
    event_title: str
    plain_text: str
    html_text: str


def _pluralize(value: int, *, one: str, few: str, many: str) -> str:
    remainder_10 = value % 10
    remainder_100 = value % 100
    if remainder_10 == 1 and remainder_100 != 11:
        return one
    if remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
        return few
    return many


def _format_duration(delta: timedelta) -> str:
    total_minutes = max(int(delta.total_seconds() // 60), 0)
    if total_minutes < 60:
        value = max(total_minutes, 1)
        return f"{value} {_pluralize(value, one='минуту', few='минуты', many='минут')}"

    total_hours = total_minutes // 60
    if total_hours < 24:
        return f"{total_hours} {_pluralize(total_hours, one='час', few='часа', many='часов')}"

    total_days = total_hours // 24
    return f"{total_days} {_pluralize(total_days, one='день', few='дня', many='дней')}"


def _headline_for_incident(
    incident: StopListIncident | None,
    *,
    changed: bool,
) -> tuple[str, str]:
    if incident is not None:
        lifecycle = str(incident.lifecycle_state or "").strip().lower()
        if lifecycle == "new":
            return "Новый стоп-лист", "новый"
        if lifecycle == "ongoing":
            return "Стоп-лист продолжается", "продолжается"
        if lifecycle == "resolved":
            return "Стоп-лист нормализовался", "нормализовался"
    if changed:
        return "Стоп-лист изменился", "изменился"
    return "Стоп-лист по расписанию", "по расписанию"


def build_stoplist_monitor_card(
    *,
    point_name: str,
    report_text: str,
    incident: StopListIncident | None,
    changed: bool,
    now: datetime | None = None,
) -> StopListMonitorCard:
    now = now or datetime.utcnow()
    headline, case_label = _headline_for_incident(incident, changed=changed)

    plain_lines = [headline, "", f"Точка: {point_name}", f"Кейс: {case_label}"]
    html_lines = [
        escape(headline),
        "",
        f"<b>Точка:</b> {escape(point_name)}",
        f"<b>Кейс:</b> {escape(case_label)}",
    ]

    needs_reaction_hint = False
    if incident is not None:
        manager_status = str(incident.manager_status or "unreviewed").strip().lower() or "unreviewed"
        manager_status_label = format_manager_status_label(manager_status)
        if incident.status == "open":
            opened_at = incident.opened_at or incident.first_seen_at or incident.last_seen_at or now
            age_label = _format_duration(max(now - opened_at, timedelta()))
            plain_lines.append(f"Реакция: {manager_status_label}")
            plain_lines.append(f"Открыт: {age_label} назад")
            html_lines.append(f"<b>Реакция:</b> {escape(manager_status_label)}")
            html_lines.append(f"<b>Открыт:</b> {escape(age_label)} назад")
            needs_reaction_hint = manager_status == "unreviewed"
        else:
            opened_at = incident.opened_at or incident.first_seen_at or now
            resolved_at = incident.resolved_at or incident.last_seen_at or now
            duration_label = _format_duration(max(resolved_at - opened_at, timedelta()))
            plain_lines.append(f"Последняя реакция: {manager_status_label}")
            plain_lines.append(f"Кейс длился: {duration_label}")
            html_lines.append(f"<b>Последняя реакция:</b> {escape(manager_status_label)}")
            html_lines.append(f"<b>Кейс длился:</b> {escape(duration_label)}")

    normalized_report = (report_text or "").strip()
    if normalized_report:
        plain_lines.extend(["", normalized_report])
        html_lines.extend(["", escape(normalized_report)])

    if needs_reaction_hint:
        hint = "Чтобы отметить статус, ответьте на это сообщение: принято / исправлено / нужна помощь."
        plain_lines.extend(["", hint])
        html_lines.extend(["", f"<i>{escape(hint)}</i>"])

    return StopListMonitorCard(
        event_title=f"{headline}: {point_name}",
        plain_text="\n".join(plain_lines).strip(),
        html_text="\n".join(html_lines).strip(),
    )
