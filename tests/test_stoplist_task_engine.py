import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.stoplist_incidents import upsert_stoplist_incident
from data_agent.stoplist_reactions import apply_stoplist_reaction
from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, SavedPoint, StopListIncident, Task, User


class StopListTaskEngineTest(unittest.TestCase):
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
                telegram_id=137236883,
                username="priority",
                first_name="Priority",
                last_name=None,
                is_bot=False,
            )
            db.add(user)
            db.flush()

            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="stoplist",
                point_name="Сухой Лог, Белинского 40",
                check_interval_minutes=180,
                is_active=True,
            )
            db.add(config)
            db.flush()

            db.add(
                SavedPoint(
                    user_id=user.id,
                    provider="italian_pizza",
                    city="Сухой Лог",
                    address="Белинского 40",
                    display_name="Сухой Лог, Белинского 40",
                    is_active=True,
                    report_delivery_enabled=True,
                    stoplist_report_chat_id=-1001001,
                    stoplist_report_chat_title="ТурбоБот Сухой Лог",
                    stats_interval_minutes=240,
                )
            )
            db.flush()

            event = DataAgentMonitorEvent(
                user_id=user.id,
                config_id=config.id,
                system_name="italian_pizza",
                monitor_type="stoplist",
                point_name="Сухой Лог, Белинского 40",
                severity="alert",
                title="Обнаружен стоп-лист: Сухой Лог, Белинского 40",
                body="report",
                event_hash="hash-1",
                sent_to_telegram=True,
                telegram_chat_id=-1001001,
                telegram_message_id=5001,
                telegram_sent_at=datetime(2026, 4, 23, 12, 0, 0),
                created_at=datetime(2026, 4, 23, 12, 0, 0),
            )
            db.add(event)
            db.flush()

            db.add(
                StopListIncident(
                    user_id=user.id,
                    monitor_config_id=config.id,
                    first_event_id=event.id,
                    last_event_id=event.id,
                    system_name="italian_pizza",
                    point_name="Сухой Лог, Белинского 40",
                    status="open",
                    lifecycle_state="new",
                    manager_status="unreviewed",
                    title="Новый стоп-лист: Сухой Лог, Белинского 40",
                    summary_text="report",
                    current_items_json=["Маргарита"],
                    last_delta_json={"added": ["Маргарита"], "removed": [], "stayed": []},
                    last_report_hash="hash-1",
                    opened_at=datetime(2026, 4, 23, 12, 0, 0),
                    first_seen_at=datetime(2026, 4, 23, 12, 0, 0),
                    last_seen_at=datetime(2026, 4, 23, 12, 0, 0),
                    update_count=1,
                )
            )
            db.commit()
            self.user_id = user.id
            self.config_id = config.id
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_accepted_reaction_creates_linked_task(self) -> None:
        db = self.SessionLocal()
        try:
            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Принято, беру в работу",
                observed_at=datetime(2026, 4, 23, 12, 5, 0),
                message_id=9001,
                reply_to_message_id=5001,
                reply_to_from_bot=True,
            )
            db.commit()
            incident = db.query(StopListIncident).one()
            task = db.query(Task).filter(Task.id == incident.linked_task_id).one()
            assignee_ids = {assignee.id for assignee in task.assignees}
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.task_action, "created")
        self.assertEqual(result.task_id, task.id)
        self.assertNotIn("Завёл задачу", result.response_text)
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.priority, "high")
        self.assertEqual(task.assigned_to, self.user_id)
        self.assertEqual(assignee_ids, {self.user_id})

    def test_escalated_reaction_creates_urgent_task(self) -> None:
        db = self.SessionLocal()
        try:
            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Эскалируй выше",
                observed_at=datetime(2026, 4, 23, 12, 7, 0),
                message_id=9002,
                reply_to_message_id=5001,
                reply_to_from_bot=True,
            )
            db.commit()
            incident = db.query(StopListIncident).one()
            task = db.query(Task).filter(Task.id == incident.linked_task_id).one()
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertEqual(result.task_action, "created")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.priority, "urgent")

    def test_resolved_incident_completes_linked_task(self) -> None:
        db = self.SessionLocal()
        try:
            apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Принято",
                observed_at=datetime(2026, 4, 23, 12, 5, 0),
                message_id=9001,
                reply_to_message_id=5001,
                reply_to_from_bot=True,
            )
            db.commit()

            config = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).one()
            incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "items": [],
                    "delta": {"added": [], "removed": ["Маргарита"], "stayed": []},
                    "report_text": "resolved",
                    "alert_hash": "hash-2",
                },
                observed_at=datetime(2026, 4, 23, 13, 0, 0),
            )
            db.commit()
            task = db.query(Task).one()
            incident_status = incident.status
            task_status = task.status
        finally:
            db.close()

        self.assertIsNotNone(incident)
        self.assertEqual(incident_status, "resolved")
        self.assertEqual(task_status, "completed")

    def test_ongoing_open_snapshot_resets_fixed_reaction(self) -> None:
        db = self.SessionLocal()
        try:
            incident = db.query(StopListIncident).one()
            incident.manager_status = "fixed"
            incident.manager_note = "Исправлено"
            incident.manager_updated_at = datetime(2026, 4, 23, 12, 10, 0)
            db.commit()

            config = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).one()
            updated_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "items": ["Маргарита"],
                    "delta": {"added": [], "removed": [], "stayed": ["Маргарита"]},
                    "report_text": "still open",
                    "alert_hash": "hash-3",
                },
                observed_at=datetime(2026, 4, 23, 13, 0, 0),
            )
            db.commit()
            manager_status = updated_incident.manager_status
            manager_note = updated_incident.manager_note
            manager_updated_at = updated_incident.manager_updated_at
        finally:
            db.close()

        self.assertIsNotNone(updated_incident)
        self.assertEqual(manager_status, "unreviewed")
        self.assertIsNone(manager_note)
        self.assertIsNone(manager_updated_at)


if __name__ == "__main__":
    unittest.main()
