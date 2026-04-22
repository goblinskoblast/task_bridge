import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.stoplist_reactions import apply_stoplist_reaction
from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, SavedPoint, StopListIncident, User


class StopListReactionFlowTest(unittest.TestCase):
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

            for point_name, city, address, chat_id in [
                ("Сухой Лог, Белинского 40", "Сухой Лог", "Белинского 40", -1001001),
                ("Полевской, Ленина 11", "Полевской", "Ленина 11", -1001002),
            ]:
                config = DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
                    point_name=point_name,
                    check_interval_minutes=180,
                    is_active=True,
                )
                db.add(config)
                db.flush()

                point = SavedPoint(
                    user_id=user.id,
                    provider="italian_pizza",
                    city=city,
                    address=address,
                    display_name=point_name,
                    is_active=True,
                    report_delivery_enabled=True,
                    stoplist_report_chat_id=chat_id,
                    stoplist_report_chat_title=f"ТурбоБот {city}",
                    stats_interval_minutes=240,
                )
                db.add(point)
                db.flush()

                event = DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
                    point_name=point_name,
                    severity="alert",
                    title=f"Обнаружен стоп-лист: {point_name}",
                    body="report",
                    event_hash=f"hash-{point_name}",
                    sent_to_telegram=True,
                    telegram_chat_id=chat_id,
                    telegram_message_id=5000 + config.id,
                    telegram_sent_at=datetime(2026, 4, 22, 12, 0, 0),
                    created_at=datetime(2026, 4, 22, 12, 0, 0),
                )
                db.add(event)
                db.flush()

                incident = StopListIncident(
                    user_id=user.id,
                    monitor_config_id=config.id,
                    first_event_id=event.id,
                    last_event_id=event.id,
                    system_name="italian_pizza",
                    point_name=point_name,
                    status="open",
                    lifecycle_state="new",
                    manager_status="unreviewed",
                    title=f"Новый стоп-лист: {point_name}",
                    summary_text="report",
                    current_items_json=["Маргарита"],
                    last_delta_json={"added": ["Маргарита"], "removed": [], "stayed": []},
                    last_report_hash=f"hash-{point_name}",
                    opened_at=datetime(2026, 4, 22, 12, 0, 0),
                    first_seen_at=datetime(2026, 4, 22, 12, 0, 0),
                    last_seen_at=datetime(2026, 4, 22, 12, 0, 0),
                    update_count=1,
                )
                db.add(incident)

            db.commit()
            self.user_id = user.id
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_apply_stoplist_reaction_matches_direct_reply_to_alert(self) -> None:
        db = self.SessionLocal()
        try:
            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Принято, беру в работу",
                observed_at=datetime(2026, 4, 22, 12, 5, 0),
                message_id=9001,
                reply_to_message_id=5001,
                reply_to_from_bot=True,
            )
            db.commit()
            incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.point_name == "Сухой Лог, Белинского 40")
                .one()
            )
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.matched)
        self.assertEqual(result.manager_status, "accepted")
        self.assertEqual(result.matched_by, "reply_to_alert")
        self.assertIn("Сухой Лог, Белинского 40", result.response_text)
        self.assertEqual(incident.manager_status, "accepted")
        self.assertEqual(incident.manager_note, "Принято, беру в работу")
        self.assertEqual(incident.manager_updated_by_user_id, self.user_id)
        self.assertEqual(incident.manager_updated_chat_id, -1001001)
        self.assertEqual(incident.manager_updated_message_id, 9001)

    def test_apply_stoplist_reaction_matches_dedicated_point_chat_without_reply(self) -> None:
        db = self.SessionLocal()
        try:
            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001002,
                text="Исправлено",
                observed_at=datetime(2026, 4, 22, 12, 10, 0),
                message_id=9002,
            )
            db.commit()
            incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.point_name == "Полевской, Ленина 11")
                .one()
            )
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.matched)
        self.assertEqual(result.manager_status, "fixed")
        self.assertEqual(result.matched_by, "point_chat")
        self.assertIn("Перепроверю по следующему циклу", result.response_text)
        self.assertEqual(incident.manager_status, "fixed")
        self.assertEqual(incident.manager_updated_message_id, 9002)

    def test_apply_stoplist_reaction_matches_explicit_point_name(self) -> None:
        db = self.SessionLocal()
        try:
            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1009999,
                text="По Полевской, Ленина 11 нужна помощь",
                observed_at=datetime(2026, 4, 22, 12, 15, 0),
                message_id=9003,
            )
            db.commit()
            dry_log_incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.point_name == "Сухой Лог, Белинского 40")
                .one()
            )
            polevskoy_incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.point_name == "Полевской, Ленина 11")
                .one()
            )
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.matched)
        self.assertEqual(result.manager_status, "needs_help")
        self.assertEqual(result.matched_by, "point_name")
        self.assertEqual(dry_log_incident.manager_status, "unreviewed")
        self.assertEqual(polevskoy_incident.manager_status, "needs_help")

    def test_apply_stoplist_reaction_returns_clarification_when_no_incident_match(self) -> None:
        db = self.SessionLocal()
        try:
            stale_incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.point_name == "Сухой Лог, Белинского 40")
                .one()
            )
            stale_incident.status = "resolved"
            stale_incident.lifecycle_state = "resolved"
            stale_incident.resolved_at = stale_incident.last_seen_at + timedelta(minutes=5)
            db.commit()

            result = apply_stoplist_reaction(
                db,
                telegram_user_id=137236883,
                chat_id=-1001001,
                text="Принято",
                observed_at=datetime(2026, 4, 22, 12, 20, 0),
                message_id=9004,
            )
            db.commit()
        finally:
            db.close()

        self.assertIsNotNone(result)
        self.assertFalse(result.matched)
        self.assertEqual(result.manager_status, "accepted")
        self.assertIn("Ответьте на сообщение бота", result.response_text)


if __name__ == "__main__":
    unittest.main()
