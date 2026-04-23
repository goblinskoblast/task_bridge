import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot import reminders
from db.models import Base, Task, User


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=1)


class ReminderSkipStoplistTasksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        db = self.SessionLocal()
        try:
            user = User(
                telegram_id=555123,
                username="tester",
                first_name="Tester",
                last_name=None,
                is_bot=False,
            )
            db.add(user)
            db.flush()

            stoplist_task = Task(
                created_by=user.id,
                assigned_to=user.id,
                title="Стоп-лист: Полевской, Ленина 11",
                description="stoplist incident task",
                status="in_progress",
                priority="high",
                due_date=datetime.utcnow() - timedelta(hours=1),
            )
            stoplist_task.assignees.append(user)

            normal_task = Task(
                created_by=user.id,
                assigned_to=user.id,
                title="Проверить поставку",
                description="обычная задача",
                status="in_progress",
                priority="high",
                due_date=datetime.utcnow() - timedelta(hours=1),
            )
            normal_task.assignees.append(user)

            db.add_all([stoplist_task, normal_task])
            db.commit()
            self.stoplist_task_id = stoplist_task.id
            self.normal_task_id = normal_task.id
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_check_and_send_reminders_skips_stoplist_linked_tasks(self) -> None:
        bot = _FakeBot()

        with patch.object(reminders, "get_db_session", side_effect=self.SessionLocal):
            asyncio.run(reminders.check_and_send_reminders(bot))

        self.assertEqual(len(bot.messages), 1)
        self.assertIn("Проверить поставку", bot.messages[0].get("text", ""))
        self.assertNotIn("Стоп-лист: Полевской, Ленина 11", bot.messages[0].get("text", ""))

        db = self.SessionLocal()
        try:
            stoplist_task = db.query(Task).filter(Task.id == self.stoplist_task_id).one()
            normal_task = db.query(Task).filter(Task.id == self.normal_task_id).one()
        finally:
            db.close()

        self.assertIsNone(stoplist_task.last_assignee_reminder_sent_at)
        self.assertIsNotNone(normal_task.last_assignee_reminder_sent_at)


if __name__ == "__main__":
    unittest.main()
