import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Task
from db.task_retention import (
    DELETE_REASON_MANUAL,
    DELETE_REASON_OVERDUE,
    cleanup_overdue_tasks,
    mark_task_deleted,
    visible_tasks,
)


class TaskRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()

    def _create_task(self, *, status: str, due_date: datetime | None) -> Task:
        task = Task(
            title=f"Task {status}",
            status=status,
            priority="normal",
            due_date=due_date,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def test_cleanup_overdue_tasks_soft_deletes_only_old_actionable_tasks(self):
        now = datetime(2026, 4, 13, 12, 0, 0)
        old_overdue = self._create_task(status="pending", due_date=now - timedelta(days=4))
        recent_overdue = self._create_task(status="pending", due_date=now - timedelta(days=2, hours=23))
        completed_old = self._create_task(status="completed", due_date=now - timedelta(days=10))
        no_deadline = self._create_task(status="in_progress", due_date=None)

        deleted = cleanup_overdue_tasks(self.db, now=now)

        self.db.refresh(old_overdue)
        self.db.refresh(recent_overdue)
        self.db.refresh(completed_old)
        self.db.refresh(no_deadline)

        self.assertEqual([task.id for task in deleted], [old_overdue.id])
        self.assertTrue(old_overdue.is_deleted)
        self.assertEqual(old_overdue.delete_reason, DELETE_REASON_OVERDUE)
        self.assertIsNotNone(old_overdue.deleted_at)

        self.assertFalse(recent_overdue.is_deleted)
        self.assertFalse(completed_old.is_deleted)
        self.assertFalse(no_deadline.is_deleted)

    def test_visible_tasks_hides_soft_deleted_rows(self):
        visible = self._create_task(status="pending", due_date=None)
        hidden = self._create_task(status="pending", due_date=None)
        mark_task_deleted(hidden, reason=DELETE_REASON_MANUAL, deleted_at=datetime(2026, 4, 13, 13, 0, 0))
        self.db.commit()

        tasks = visible_tasks(self.db.query(Task)).order_by(Task.id.asc()).all()

        self.assertEqual([task.id for task in tasks], [visible.id])


if __name__ == "__main__":
    unittest.main()
