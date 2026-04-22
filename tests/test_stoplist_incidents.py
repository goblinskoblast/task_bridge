import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.stoplist_incidents import upsert_stoplist_incident
from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, StopListIncident, User


class StopListIncidentLifecycleTest(unittest.TestCase):
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
            db.commit()
            db.refresh(config)
            self.user_id = user.id
            self.config_id = config.id
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_event(self, db, *, created_at: datetime) -> DataAgentMonitorEvent:
        event = DataAgentMonitorEvent(
            user_id=self.user_id,
            config_id=self.config_id,
            system_name="italian_pizza",
            monitor_type="stoplist",
            point_name="Сухой Лог, Белинского 40",
            severity="info",
            title="Стоп-лист по расписанию: Сухой Лог, Белинского 40",
            body="report",
            event_hash=f"hash-{created_at.isoformat()}",
            sent_to_telegram=False,
            created_at=created_at,
        )
        db.add(event)
        db.flush()
        return event

    def _load_config(self, db) -> DataAgentMonitorConfig:
        return db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()

    def test_creates_new_stoplist_incident_for_first_active_snapshot(self) -> None:
        observed_at = datetime(2026, 4, 22, 10, 0, 0)
        db = self.SessionLocal()
        try:
            config = self._load_config(db)
            event = self._create_event(db, created_at=observed_at)
            incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист:\n- Маргарита\n- Пепперони",
                    "items": ["Маргарита", "Пепперони"],
                    "delta": {"added": ["Маргарита", "Пепперони"], "removed": [], "stayed": []},
                },
                monitor_event=event,
                observed_at=observed_at,
            )
            db.commit()
        finally:
            db.close()

        db = self.SessionLocal()
        try:
            rows = db.query(StopListIncident).all()
        finally:
            db.close()

        self.assertIsNotNone(incident)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "open")
        self.assertEqual(rows[0].lifecycle_state, "new")
        self.assertEqual(rows[0].manager_status, "unreviewed")
        self.assertEqual(rows[0].current_items_json, ["Маргарита", "Пепперони"])
        self.assertEqual(rows[0].update_count, 1)
        self.assertEqual(rows[0].first_event_id, rows[0].last_event_id)

    def test_updates_existing_incident_as_ongoing(self) -> None:
        opened_at = datetime(2026, 4, 22, 10, 0, 0)
        next_seen_at = opened_at + timedelta(hours=3)
        db = self.SessionLocal()
        try:
            config = self._load_config(db)
            first_event = self._create_event(db, created_at=opened_at)
            first_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "first report",
                    "items": ["Маргарита"],
                    "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
                },
                monitor_event=first_event,
                observed_at=opened_at,
            )
            second_event = self._create_event(db, created_at=next_seen_at)
            second_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "second report",
                    "items": ["Маргарита", "Пепперони"],
                    "delta": {"added": ["Пепперони"], "removed": [], "stayed": ["Маргарита"]},
                },
                monitor_event=second_event,
                observed_at=next_seen_at,
            )
            first_incident_id = first_incident.id
            second_incident_id = second_incident.id
            second_event_id = second_event.id
            db.commit()
        finally:
            db.close()

        db = self.SessionLocal()
        try:
            row = db.query(StopListIncident).one()
        finally:
            db.close()

        self.assertEqual(first_incident_id, second_incident_id)
        self.assertEqual(row.status, "open")
        self.assertEqual(row.lifecycle_state, "ongoing")
        self.assertEqual(row.current_items_json, ["Маргарита", "Пепперони"])
        self.assertEqual(row.last_delta_json, {"added": ["Пепперони"], "removed": [], "stayed": ["Маргарита"]})
        self.assertEqual(row.update_count, 2)
        self.assertEqual(row.last_event_id, second_event_id)
        self.assertEqual(row.resolved_at, None)

    def test_resolves_existing_incident_when_stoplist_clears(self) -> None:
        opened_at = datetime(2026, 4, 22, 10, 0, 0)
        resolved_at = opened_at + timedelta(hours=6)
        db = self.SessionLocal()
        try:
            config = self._load_config(db)
            first_event = self._create_event(db, created_at=opened_at)
            incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "first report",
                    "items": ["Маргарита"],
                    "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
                },
                monitor_event=first_event,
                observed_at=opened_at,
            )
            resolved_event = self._create_event(db, created_at=resolved_at)
            resolved_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист: недоступных позиций не найдено.",
                    "items": [],
                    "delta": {"added": [], "removed": ["Маргарита"], "stayed": []},
                },
                monitor_event=resolved_event,
                observed_at=resolved_at,
            )
            incident_id = incident.id
            resolved_incident_id = resolved_incident.id
            resolved_event_id = resolved_event.id
            db.commit()
        finally:
            db.close()

        db = self.SessionLocal()
        try:
            row = db.query(StopListIncident).one()
        finally:
            db.close()

        self.assertEqual(incident_id, resolved_incident_id)
        self.assertEqual(row.status, "resolved")
        self.assertEqual(row.lifecycle_state, "resolved")
        self.assertEqual(row.current_items_json, [])
        self.assertEqual(row.last_delta_json, {"added": [], "removed": ["Маргарита"], "stayed": []})
        self.assertEqual(row.last_event_id, resolved_event_id)
        self.assertIsNotNone(row.resolved_at)
        self.assertEqual(row.update_count, 2)

    def test_creates_new_incident_after_previous_one_was_resolved(self) -> None:
        opened_at = datetime(2026, 4, 22, 10, 0, 0)
        resolved_at = opened_at + timedelta(hours=6)
        reopened_at = resolved_at + timedelta(hours=3)
        db = self.SessionLocal()
        try:
            config = self._load_config(db)
            first_event = self._create_event(db, created_at=opened_at)
            first_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "first report",
                    "items": ["Маргарита"],
                    "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
                },
                monitor_event=first_event,
                observed_at=opened_at,
            )
            resolved_event = self._create_event(db, created_at=resolved_at)
            upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "resolved report",
                    "items": [],
                    "delta": {"added": [], "removed": ["Маргарита"], "stayed": []},
                },
                monitor_event=resolved_event,
                observed_at=resolved_at,
            )
            reopened_event = self._create_event(db, created_at=reopened_at)
            reopened_incident = upsert_stoplist_incident(
                db,
                config=config,
                result={
                    "report_text": "reopened report",
                    "items": ["Пепперони"],
                    "delta": {"added": ["Пепперони"], "removed": [], "stayed": []},
                },
                monitor_event=reopened_event,
                observed_at=reopened_at,
            )
            first_incident_id = first_incident.id
            reopened_incident_id = reopened_incident.id
            db.commit()
        finally:
            db.close()

        db = self.SessionLocal()
        try:
            rows = db.query(StopListIncident).order_by(StopListIncident.id.asc()).all()
        finally:
            db.close()

        self.assertEqual(len(rows), 2)
        self.assertNotEqual(first_incident_id, reopened_incident_id)
        self.assertEqual(rows[0].status, "resolved")
        self.assertEqual(rows[1].status, "open")
        self.assertEqual(rows[1].lifecycle_state, "new")
        self.assertEqual(rows[1].current_items_json, ["Пепперони"])


if __name__ == "__main__":
    unittest.main()
