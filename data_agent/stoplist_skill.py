from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from db.models import StopListIncident

from .stoplist_digest import describe_open_stoplist_incident
from .stoplist_reactions import format_manager_status_label


@dataclass(frozen=True)
class StopListSkillPointStatus:
    point_name: str
    is_open: bool
    status_label: str
    manager_status_label: str
    task_status_label: str | None
    age_label: str
    updates_count: int
    requires_attention: bool


@dataclass(frozen=True)
class StopListSkillSnapshot:
    days: int
    total_incidents: int
    open_points: int
    attention_points: int
    in_progress_points: int
    recent_resolved_points: int
    point_statuses: list[StopListSkillPointStatus]


def _format_task_status_label(task) -> str | None:
    if task is None:
        return None
    normalized = str(getattr(task, "status", None) or "").strip().lower()
    if normalized == "pending":
        return "задача создана"
    if normalized == "in_progress":
        return "задача в работе"
    if normalized == "completed":
        return "задача закрыта"
    if normalized == "cancelled":
        return "задача снята"
    return None


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


def _build_point_status(
    point_name: str,
    rows: list[StopListIncident],
    *,
    now: datetime,
) -> StopListSkillPointStatus:
    rows.sort(
        key=lambda item: (
            item.status != "open",
            -(item.last_seen_at.timestamp() if item.last_seen_at else 0),
            -int(item.id or 0),
        )
    )
    open_incident = next((item for item in rows if item.status == "open"), None)
    latest = rows[0]

    if open_incident is not None:
        meta = describe_open_stoplist_incident(open_incident, now=now) or {}
        manager_status = str(open_incident.manager_status or "unreviewed").strip().lower() or "unreviewed"
        task_status_label = _format_task_status_label(getattr(open_incident, "linked_task", None))
        opened_at = open_incident.opened_at or open_incident.first_seen_at or open_incident.last_seen_at or now
        return StopListSkillPointStatus(
            point_name=point_name,
            is_open=True,
            status_label=str(meta.get("status_label") or "есть открытый стоп-лист"),
            manager_status_label=str(meta.get("manager_status_label") or format_manager_status_label(manager_status)),
            task_status_label=task_status_label,
            age_label=_format_duration(max(now - opened_at, timedelta())),
            updates_count=max(int(open_incident.update_count or 0), 1),
            requires_attention=manager_status in {"unreviewed", "needs_help", "escalated"},
        )

    manager_status = str(latest.manager_status or "unreviewed").strip().lower() or "unreviewed"
    resolved_at = latest.resolved_at or latest.last_seen_at or latest.opened_at or now
    return StopListSkillPointStatus(
        point_name=point_name,
        is_open=False,
        status_label="открытых кейсов сейчас нет",
        manager_status_label=format_manager_status_label(manager_status),
        task_status_label=_format_task_status_label(getattr(latest, "linked_task", None)),
        age_label=_format_duration(max(now - resolved_at, timedelta())),
        updates_count=max(int(latest.update_count or 0), 1),
        requires_attention=False,
    )


def build_stoplist_skill_snapshot(
    incidents: Iterable[StopListIncident],
    *,
    days: int = 7,
    now: datetime | None = None,
) -> StopListSkillSnapshot:
    now = now or datetime.utcnow()
    rows = list(incidents)
    if not rows:
        return StopListSkillSnapshot(
            days=days,
            total_incidents=0,
            open_points=0,
            attention_points=0,
            in_progress_points=0,
            recent_resolved_points=0,
            point_statuses=[],
        )

    grouped: dict[str, list[StopListIncident]] = {}
    for row in rows:
        grouped.setdefault(str(row.point_name), []).append(row)

    point_statuses = [
        _build_point_status(point_name, point_rows, now=now)
        for point_name, point_rows in grouped.items()
    ]
    point_statuses.sort(
        key=lambda item: (
            not item.is_open,
            not item.requires_attention,
            item.manager_status_label != "принято",
            item.point_name,
        )
    )

    return StopListSkillSnapshot(
        days=days,
        total_incidents=len(rows),
        open_points=sum(1 for item in point_statuses if item.is_open),
        attention_points=sum(1 for item in point_statuses if item.requires_attention),
        in_progress_points=sum(1 for item in point_statuses if item.is_open and item.manager_status_label == "принято"),
        recent_resolved_points=sum(1 for item in point_statuses if not item.is_open),
        point_statuses=point_statuses,
    )


def format_stoplist_skill_answer(
    snapshot: StopListSkillSnapshot,
    *,
    focus: str = "overview",
    point_name: str | None = None,
) -> str:
    focus = str(focus or "overview").strip().lower() or "overview"
    if point_name:
        point_status = next(
            (item for item in snapshot.point_statuses if item.point_name == point_name),
            None,
        )
        if point_status is None:
            return (
                f"По точке {point_name} открытых кейсов по стоп-листу сейчас не вижу. "
                f"Истории за последние {snapshot.days} {_pluralize(snapshot.days, one='день', few='дня', many='дней')} тоже нет."
            )
        if point_status.is_open:
            task_part = f"Задача: {point_status.task_status_label}. " if point_status.task_status_label else ""
            return (
                f"По точке {point_status.point_name} сейчас открытый кейс по стоп-листу. "
                f"Статус: {point_status.status_label}. "
                f"Реакция: {point_status.manager_status_label}. "
                f"{task_part}"
                f"Открыт {point_status.age_label} назад. "
                f"Обновлялся {point_status.updates_count} {_pluralize(point_status.updates_count, one='раз', few='раза', many='раз')}."
            )
        return (
            f"По точке {point_status.point_name} открытых кейсов по стоп-листу сейчас нет. "
            f"Последний кейс нормализовался {point_status.age_label} назад."
        )

    if focus == "attention":
        attention_items = [item for item in snapshot.point_statuses if item.requires_attention]
        if not attention_items:
            return "По стоп-листу сейчас нет кейсов, которые требуют реакции."

        lines = [f"По стоп-листу сейчас требуют реакции {len(attention_items)} {_pluralize(len(attention_items), one='кейс', few='кейса', many='кейсов')}:"]
        for index, item in enumerate(attention_items, start=1):
            task_suffix = f"; {item.task_status_label}" if item.task_status_label else ""
            lines.append(
                f"{index}. {item.point_name} — {item.status_label}{task_suffix}; открыт {item.age_label} назад."
            )
        return "\n".join(lines)

    if snapshot.total_incidents <= 0:
        return f"По стоп-листу за последние {snapshot.days} {_pluralize(snapshot.days, one='день', few='дня', many='дней')} кейсов не было."

    lines = [
        "Сейчас по стоп-листу:",
        f"• Открыто: {snapshot.open_points}",
        f"• Требуют реакции: {snapshot.attention_points}",
        f"• В работе: {snapshot.in_progress_points}",
    ]
    if snapshot.recent_resolved_points:
        lines.append(f"• Недавно нормализовались: {snapshot.recent_resolved_points}")

    open_items = [item for item in snapshot.point_statuses if item.is_open]
    if open_items:
        lines.append("")
        for index, item in enumerate(open_items[:5], start=1):
            task_suffix = f"; задача: {item.task_status_label}" if item.task_status_label else ""
            lines.append(
                f"{index}. {item.point_name} — {item.status_label}; реакция: {item.manager_status_label}{task_suffix}; открыт {item.age_label} назад."
            )
    else:
        lines.append("")
        lines.append("Открытых кейсов сейчас нет.")
    return "\n".join(lines)
