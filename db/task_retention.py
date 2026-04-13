from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Query, Session

from db.models import Task


OVERDUE_AUTO_DELETE_GRACE_DAYS = 3
DELETE_REASON_MANUAL = "manual"
DELETE_REASON_OVERDUE = "overdue_retention"


def visible_tasks(query: Query) -> Query:
    return query.filter(Task.is_deleted.is_(False))


def actionable_tasks(query: Query) -> Query:
    return visible_tasks(query).filter(Task.status.in_(["pending", "in_progress"]))


def mark_task_deleted(task: Task, *, reason: str, deleted_at: datetime | None = None) -> Task:
    task.is_deleted = True
    task.deleted_at = deleted_at or datetime.utcnow()
    task.delete_reason = reason
    return task


def cleanup_overdue_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    grace_days: int = OVERDUE_AUTO_DELETE_GRACE_DAYS,
) -> list[Task]:
    current_time = now or datetime.utcnow()
    overdue_cutoff = current_time - timedelta(days=grace_days)

    tasks = (
        actionable_tasks(db.query(Task))
        .filter(Task.due_date.isnot(None))
        .filter(Task.due_date < overdue_cutoff)
        .all()
    )

    for task in tasks:
        mark_task_deleted(task, reason=DELETE_REASON_OVERDUE, deleted_at=current_time)

    if tasks:
        db.commit()

    return tasks
