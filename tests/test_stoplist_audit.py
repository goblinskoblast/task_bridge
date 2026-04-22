import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.stoplist_incidents import upsert_stoplist_incident
from data_agent.stoplist_reactions import apply_stoplist_reaction
from db.models import (
    Base,
    DataAgentMonitorConfig,
    DataAgentMonitorEvent,
    SavedPoint,
    StopListIncident,
    StopListIncidentAuditEntry,
    User,
)


class StopListAuditTest(unittest.TestCase):
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
            db.commit()
            self.user_id = user.id
            self.config_id = config.id
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_event(self, db, *, message_id: int, created_at: datetime) -> DataAgentMonitorEvent:
        event = DataAgentMonitorEvent(
            user_id=self.user_id,
            config_id=self.config_id,
            system_name="italian_pizza",
            monitor_type="stoplist",
            point_name="Сухой Лог, Белинского 40",
            severity="info",
            title="event",
            body="body",
            event_hash=f"hash-{message_id}",
            sent_to_telegram=True,
            telegram_chat_id=-1001001,
            telegram_message_id=message_id,
            telegram_sent_at=created_at,
            created_at=created_at,
        )
        db.add(event)
        db.flush()
        return event

    def test_incident_reaction_and_resolve_write_business_audit_trail(self) -> None:
        db = self.SessionLocal()
        try:
            config = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).one()
            first_event = self._create_event(db, message_id=5001, created_at=datetime(2026, 4, 23, 12, 0, 0))
            incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "items": ["Маргарита"],
                    "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
                    "report_text": "opened",
                    "alert_hash": "hash-open",
                },
                monitor_event=first_event,
                observed_at=datetime(2026, 4, 23, 12, 0, 0),
            )
            db.commit()

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

            second_event = self._create_event(db, message_id=5002, created_at=datetime(2026, 4, 23, 13, 0, 0))
            upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "items": [],
                    "delta": {"added": [], "removed": ["Маргарита"], "stayed": []},
                    "report_text": "resolved",
                    "alert_hash": "hash-resolved",
                },
                monitor_event=second_event,
                observed_at=datetime(2026, 4, 23, 13, 0, 0),
            )
            db.commit()

            entries = (
                db.query(StopListIncidentAuditEntry)
                .filter(StopListIncidentAuditEntry.incident_id == incident.id)
                .order_by(StopListIncidentAuditEntry.created_at.asc(), StopListIncidentAuditEntry.id.asc())
                .all()
            )
        finally:
            db.close()

        event_types = [item.event_type for item in entries]
        self.assertEqual(
            event_types,
            [
                "incident_opened",
                "manager_reaction",
                "task_created",
                "incident_resolved",
                "task_completed",
            ],
        )
        self.assertIn("Открыт новый кейс", entries[0].summary_text)
        self.assertEqual(entries[1].payload_json.get("manager_status"), "accepted")
        self.assertEqual(entries[2].payload_json.get("task_action"), "created")
        self.assertEqual(entries[4].payload_json.get("task_status"), "completed")

    def test_needs_help_reaction_writes_attention_audit_payload(self) -> None:
        db = self.SessionLocal()
        try:
            config = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).one()
            first_event = self._create_event(db, message_id=5001, created_at=datetime(2026, 4, 23, 12, 0, 0))
            incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "items": ["Маргарита"],
                    "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
                    "report_text": "opened",
                    "alert_hash": "hash-open",
                },
                monitor_event=first_event,
                observed_at=datetime(2026, 4, 23, 12, 0, 0),
            )
            db.commit()

            apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Нужна помощь",
                observed_at=datetime(2026, 4, 23, 12, 6, 0),
                message_id=9002,
                reply_to_message_id=5001,
                reply_to_from_bot=True,
            )
            db.commit()

            entries = (
                db.query(StopListIncidentAuditEntry)
                .filter(StopListIncidentAuditEntry.incident_id == incident.id)
                .order_by(StopListIncidentAuditEntry.created_at.asc(), StopListIncidentAuditEntry.id.asc())
                .all()
            )
        finally:
            db.close()

        self.assertEqual(entries[1].event_type, "manager_reaction")
        self.assertEqual(entries[1].payload_json.get("manager_status"), "needs_help")
        self.assertEqual(entries[1].payload_json.get("matched_by"), "reply_to_alert")
        self.assertEqual(entries[2].event_type, "task_created")
        self.assertEqual(entries[2].payload_json.get("task_status"), "pending")


if __name__ == "__main__":
    unittest.main()
