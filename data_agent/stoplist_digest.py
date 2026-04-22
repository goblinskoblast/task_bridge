from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from db.models import StopListIncident

from .stoplist_reactions import format_manager_status_label


@dataclass(frozen=True)
class StopListDigestPointItem:
    point_name: str
    incidents_count: int
    update_count: int
    has_open_incident: bool
    manager_status: str
    manager_status_label: str
    incident_label: str
    last_seen_at: datetime | None


@dataclass(frozen=True)
class StopListDigestSnapshot:
    days: int
    total_incidents: int
    affected_points: int
    open_incidents: int
    recurring_points: int
    need_attention_points: int
    point_items: list[StopListDigestPointItem]


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


def describe_open_stoplist_incident(
    incident: StopListIncident | None,
    *,
    now: datetime | None = None,
) -> dict[str, str] | None:
    if incident is None or incident.status != "open":
        return None

    now = now or datetime.utcnow()
    manager_status = str(incident.manager_status or "unreviewed").strip().lower() or "unreviewed"
    manager_status_label = format_manager_status_label(manager_status)
    if manager_status == "accepted":
        status_label = "в работе у управляющего"
        tone = "info"
    elif manager_status == "fixed":
        status_label = "отмечено как исправлено"
        tone = "info"
    elif manager_status == "not_relevant":
        status_label = "отмечено как неактуально"
        tone = "info"
    elif manager_status == "needs_help":
        status_label = "по кейсу нужна помощь"
        tone = "alert"
    elif manager_status == "escalated":
        status_label = "кейс эскалирован"
        tone = "alert"
    else:
        status_label = "есть открытый стоп-лист"
        tone = "notice"

    opened_at = incident.opened_at or incident.first_seen_at or incident.last_seen_at or now
    age_label = _format_duration(max(now - opened_at, timedelta()))
    update_count = max(int(incident.update_count or 0), 1)
    incident_label = (
        f"открыт {age_label}; реакция: {manager_status_label}; "
        f"обновлялся {update_count} {_pluralize(update_count, one='раз', few='раза', many='раз')}"
    )
    return {
        "status_label": status_label,
        "status_tone": tone,
        "manager_status_label": manager_status_label,
        "incident_label": incident_label,
    }


def build_stoplist_digest_snapshot(
    incidents: Iterable[StopListIncident],
    *,
    days: int = 7,
    now: datetime | None = None,
) -> StopListDigestSnapshot:
    now = now or datetime.utcnow()
    rows = list(incidents)
    if not rows:
        return StopListDigestSnapshot(
            days=days,
            total_incidents=0,
            affected_points=0,
            open_incidents=0,
            recurring_points=0,
            need_attention_points=0,
            point_items=[],
        )

    grouped: dict[str, list[StopListIncident]] = {}
    for row in rows:
        grouped.setdefault(str(row.point_name), []).append(row)

    point_items: list[StopListDigestPointItem] = []
    need_attention_points = 0
    open_incidents = sum(1 for row in rows if row.status == "open")
    for point_name, point_rows in grouped.items():
        point_rows.sort(
            key=lambda item: (
                item.status != "open",
                -(item.last_seen_at.timestamp() if item.last_seen_at else 0),
                -int(item.id or 0),
            )
        )
        latest = point_rows[0]
        open_incident = next((item for item in point_rows if item.status == "open"), None)
        described = describe_open_stoplist_incident(open_incident, now=now)
        manager_status = str((open_incident or latest).manager_status or "unreviewed").strip().lower() or "unreviewed"
        manager_status_label = format_manager_status_label(manager_status)
        if described:
            incident_label = described["incident_label"]
            if manager_status in {"unreviewed", "needs_help", "escalated"}:
                need_attention_points += 1
        else:
            last_seen_at = latest.last_seen_at or latest.resolved_at or latest.opened_at or now
            ago_label = _format_duration(max(now - last_seen_at, timedelta()))
            incident_label = f"закрыт; последний кейс был {ago_label} назад"

        point_items.append(
            StopListDigestPointItem(
                point_name=point_name,
                incidents_count=len(point_rows),
                update_count=sum(max(int(item.update_count or 0), 1) for item in point_rows),
                has_open_incident=open_incident is not None,
                manager_status=manager_status,
                manager_status_label=manager_status_label,
                incident_label=incident_label,
                last_seen_at=(open_incident or latest).last_seen_at,
            )
        )

    point_items.sort(
        key=lambda item: (
            not item.has_open_incident,
            item.manager_status not in {"unreviewed", "needs_help", "escalated"},
            -item.incidents_count,
            item.point_name,
        )
    )

    recurring_points = sum(1 for rows in grouped.values() if len(rows) >= 2)
    return StopListDigestSnapshot(
        days=days,
        total_incidents=len(rows),
        affected_points=len(grouped),
        open_incidents=open_incidents,
        recurring_points=recurring_points,
        need_attention_points=need_attention_points,
        point_items=point_items,
    )


def format_stoplist_digest_text(snapshot: StopListDigestSnapshot) -> str:
    if snapshot.total_incidents <= 0:
        return f"За последние {snapshot.days} дней по стоп-листу инцидентов не было."

    lines = [
        f"Стоп-лист за последние {snapshot.days} дней:",
        f"• Инцидентов: {snapshot.total_incidents}",
        f"• Точек с кейсами: {snapshot.affected_points}",
        f"• Сейчас открыто: {snapshot.open_incidents}",
        f"• Повторялись: {snapshot.recurring_points}",
    ]
    if snapshot.need_attention_points:
        lines.append(f"• Нужна реакция: {snapshot.need_attention_points}")

    lines.append("")
    for index, item in enumerate(snapshot.point_items, start=1):
        incident_word = _pluralize(item.incidents_count, one="инцидент", few="инцидента", many="инцидентов")
        lines.append(
            f"{index}. {item.point_name} — {item.incidents_count} {incident_word}, {item.incident_label}"
        )

    return "\n".join(lines)
