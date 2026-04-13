import re
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from db.models import Task, User
from db.task_retention import visible_tasks


TASK_REFERENCE_PATTERNS = [
    re.compile(r"#task\s*(\d+)", flags=re.IGNORECASE),
    re.compile(r"\btask\s*[:#]?\s*(\d+)\b", flags=re.IGNORECASE),
    re.compile(r"\bзадач[аеиу]?\s*#?\s*(\d+)\b", flags=re.IGNORECASE),
]


def extract_task_reference(text: Optional[str]) -> Optional[int]:
    if not text:
        return None

    for pattern in TASK_REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))

    return None


def get_user_in_progress_tasks(db: Session, user_id: int) -> List[Task]:
    return (
        visible_tasks(db.query(Task))
        .join(Task.assignees)
        .filter(
            User.id == user_id,
            Task.status == "in_progress",
        )
        .all()
    )


def build_file_upload_task_hint(tasks: List[Task]) -> str:
    visible_tasks = sorted(
        tasks,
        key=lambda item: item.updated_at or item.created_at or datetime.min,
        reverse=True,
    )[:5]
    task_lines = "\n".join(f"• #{task.id} {task.title}" for task in visible_tasks)

    return (
        "⚠️ У вас несколько задач в работе, поэтому я не буду гадать, к какой прикрепить файл.\n\n"
        "Добавьте в подпись к файлу ссылку на задачу, например: #task123\n\n"
        f"Сейчас у вас активны:\n{task_lines}"
    )


def resolve_task_for_file_upload(
    db: Session,
    user_id: int,
    caption: Optional[str],
) -> tuple[Optional[Task], Optional[str]]:
    active_tasks = get_user_in_progress_tasks(db, user_id)

    if not active_tasks:
        return None, (
            "❌ У вас нет задач в процессе выполнения.\n\n"
            "Сначала начните выполнение задачи, нажав кнопку '▶️ Начать выполнение'."
        )

    referenced_task_id = extract_task_reference(caption)
    if referenced_task_id is not None:
        matched_task = next((task for task in active_tasks if task.id == referenced_task_id), None)
        if matched_task is not None:
            return matched_task, None

        return None, (
            f"❌ Задача #{referenced_task_id} не найдена среди ваших задач в работе.\n\n"
            f"{build_file_upload_task_hint(active_tasks)}"
        )

    if len(active_tasks) == 1:
        return active_tasks[0], None

    return None, build_file_upload_task_hint(active_tasks)
