from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from db.models import StopListIncident, Task, User

_ACTIVE_TASK_MANAGER_STATUSES = {"accepted", "needs_help", "escalated"}
_TASK_PRIORITY_BY_MANAGER_STATUS = {
    "accepted": "high",
    "needs_help": "high",
    "escalated": "urgent",
}
_TASK_STATUS_BY_MANAGER_STATUS = {
    "accepted": "in_progress",
    "needs_help": "pending",
    "escalated": "pending",
}
_TASK_DUE_HOURS_BY_MANAGER_STATUS = {
    "accepted": 4,
    "needs_help": 2,
    "escalated": 1,
}
_CASE_LABELS = {
    "new": "новый кейс",
    "ongoing": "кейс продолжается",
    "resolved": "кейс нормализовался",
}
_MANAGER_STATUS_LABELS = {
    "unreviewed": "без реакции",
    "accepted": "принято",
    "fixed": "исправлено",
    "not_relevant": "неактуально",
    "needs_help": "нужна помощь",
    "escalated": "эскалировано",
}


@dataclass(frozen=True)
class StopListTaskSyncResult:
    task_id: int | None
    action: str
    task_status: str | None


def _normalize_manager_status(value: str | None) -> str:
    return str(value or "unreviewed").strip().lower() or "unreviewed"


def _load_task(db, incident: StopListIncident) -> Task | None:
    task_id = getattr(incident, "linked_task_id", None)
    if not task_id:
        return None
    task = getattr(incident, "linked_task", None)
    if task is not None and getattr(task, "id", None) == task_id:
        return task
    return db.query(Task).filter(Task.id == task_id).first()


def _load_incident_user(db, incident: StopListIncident) -> User | None:
    user = getattr(incident, "user", None)
    if user is not None and getattr(user, "id", None) == incident.user_id:
        return user
    return db.query(User).filter(User.id == incident.user_id).first()


def _task_title(point_name: str) -> str:
    return f"Стоп-лист: {point_name}"


def _preview_items(items: list[str] | None) -> str:
    normalized = [str(item or "").strip() for item in list(items or []) if str(item or "").strip()]
    if not normalized:
        return "нет активных позиций"
    if len(normalized) <= 5:
        return ", ".join(normalized)
    return f"{', '.join(normalized[:5])} и ещё {len(normalized) - 5}"


def _task_description(incident: StopListIncident, *, observed_at: datetime) -> str:
    manager_status = _normalize_manager_status(incident.manager_status)
    lifecycle_state = str(incident.lifecycle_state or "new").strip().lower() or "new"
    opened_at = incident.opened_at or incident.first_seen_at or observed_at
    last_seen_at = incident.last_seen_at or observed_at
    lines = [
        "Инцидент по стоп-листу.",
        f"Точка: {incident.point_name}",
        f"Статус кейса: {_CASE_LABELS.get(lifecycle_state, 'активный кейс')}",
        f"Реакция: {_MANAGER_STATUS_LABELS.get(manager_status, 'статус не уточнён')}",
        f"Недоступные позиции: {_preview_items(getattr(incident, 'current_items_json', None))}",
        f"Открыт: {opened_at.strftime('%d.%m.%Y %H:%M')}",
        f"Последнее обновление: {last_seen_at.strftime('%d.%m.%Y %H:%M')}",
    ]
    manager_note = str(getattr(incident, "manager_note", None) or "").strip()
    if manager_note:
        lines.append(f"Комментарий управляющего: {manager_note}")
    summary_text = str(getattr(incident, "summary_text", None) or "").strip()
    if summary_text:
        lines.append("")
        lines.append("Сводка:")
        lines.append(summary_text[:1200])
    return "\n".join(lines)


def _ensure_task_assignee(task: Task, user: User | None) -> None:
    if user is None:
        return
    task.assigned_to = user.id
    assignee_ids = {int(assignee.id) for assignee in list(task.assignees or []) if getattr(assignee, "id", None) is not None}
    if user.id not in assignee_ids:
        task.assignees.append(user)


def _upsert_open_task(db, incident: StopListIncident, *, observed_at: datetime) -> StopListTaskSyncResult:
    manager_status = _normalize_manager_status(incident.manager_status)
    desired_status = _TASK_STATUS_BY_MANAGER_STATUS.get(manager_status, "pending")
    priority = _TASK_PRIORITY_BY_MANAGER_STATUS.get(manager_status, "high")
    due_hours = _TASK_DUE_HOURS_BY_MANAGER_STATUS.get(manager_status, 4)
    due_date = observed_at + timedelta(hours=due_hours)
    title = _task_title(incident.point_name)
    description = _task_description(incident, observed_at=observed_at)
    task = _load_task(db, incident)
    user = _load_incident_user(db, incident)

    if task is None:
        task = Task(
            created_by=incident.user_id,
            assigned_to=incident.user_id,
            title=title,
            description=description,
            status=desired_status,
            priority=priority,
            due_date=due_date,
        )
        db.add(task)
        db.flush()
        _ensure_task_assignee(task, user)
        incident.linked_task_id = int(task.id)
        incident.task_last_synced_at = observed_at
        db.flush()
        return StopListTaskSyncResult(task_id=int(task.id), action="created", task_status=task.status)

    previous_status = str(task.status or "").strip().lower()
    task.title = title
    task.description = description
    task.priority = priority
    task.due_date = due_date
    task.created_by = incident.user_id
    _ensure_task_assignee(task, user)
    task.status = desired_status
    incident.linked_task_id = int(task.id)
    incident.task_last_synced_at = observed_at
    db.flush()

    action = "reopened" if previous_status in {"completed", "cancelled"} else "updated"
    return StopListTaskSyncResult(task_id=int(task.id), action=action, task_status=task.status)


def _close_task(incident: StopListIncident, task: Task, *, status: str, observed_at: datetime) -> StopListTaskSyncResult:
    task.title = _task_title(incident.point_name)
    task.description = _task_description(incident, observed_at=observed_at)
    task.status = status
    incident.linked_task_id = int(task.id)
    incident.task_last_synced_at = observed_at
    action = "completed" if status == "completed" else "cancelled"
    return StopListTaskSyncResult(task_id=int(task.id), action=action, task_status=status)


def sync_stoplist_incident_task(
    db,
    *,
    incident: StopListIncident | None,
    observed_at: datetime | None = None,
) -> StopListTaskSyncResult:
    observed_at = observed_at or datetime.utcnow()
    if incident is None:
        return StopListTaskSyncResult(task_id=None, action="none", task_status=None)

    manager_status = _normalize_manager_status(incident.manager_status)
    if incident.status == "open" and manager_status in _ACTIVE_TASK_MANAGER_STATUSES:
        return _upsert_open_task(db, incident, observed_at=observed_at)

    task = _load_task(db, incident)
    if task is None:
        incident.task_last_synced_at = observed_at
        db.flush()
        return StopListTaskSyncResult(task_id=None, action="none", task_status=None)

    if incident.status != "open" or manager_status == "fixed":
        result = _close_task(incident, task, status="completed", observed_at=observed_at)
        db.flush()
        return result
    if manager_status == "not_relevant":
        result = _close_task(incident, task, status="cancelled", observed_at=observed_at)
        db.flush()
        return result

    incident.task_last_synced_at = observed_at
    db.flush()
    return StopListTaskSyncResult(task_id=int(task.id), action="none", task_status=task.status)


def format_stoplist_task_followup(sync_result: StopListTaskSyncResult | None) -> str | None:
    if sync_result is None or not sync_result.task_id:
        return None
    if sync_result.action == "created":
        return "Завёл задачу, чтобы кейс не потерялся."
    if sync_result.action == "reopened":
        return "Вернул связанную задачу в работу."
    if sync_result.action == "updated":
        return "Обновил связанную задачу."
    if sync_result.action == "completed":
        return "Связанную задачу закрыл."
    if sync_result.action == "cancelled":
        return "Связанную задачу снял."
    return None
