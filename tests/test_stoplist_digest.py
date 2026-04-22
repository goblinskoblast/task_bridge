import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.agent_runtime import AgentSessionSnapshot, DataAgentRuntime
from data_agent.models import DataAgentChatRequest
from data_agent.service import DataAgentService
from data_agent.stoplist_digest import build_stoplist_digest_snapshot, format_stoplist_digest_text
from db.models import Base, DataAgentMonitorConfig, StopListIncident, User


class StopListDigestFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = DataAgentRuntime()
        self.service = DataAgentService()
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

            now = datetime(2026, 4, 22, 15, 0, 0)
            for idx, point_name in enumerate(
                [
                    "Сухой Лог, Белинского 40",
                    "Реж, Ленина 17",
                ],
                start=1,
            ):
                db.add(
                    DataAgentMonitorConfig(
                        id=idx,
                        user_id=user.id,
                        system_name="italian_pizza",
                        monitor_type="stoplist",
                        point_name=point_name,
                        check_interval_minutes=180,
                        is_active=True,
                        last_status="completed",
                        last_checked_at=now - timedelta(hours=1),
                    )
                )

            db.flush()
            db.add_all(
                [
                    StopListIncident(
                        user_id=user.id,
                        monitor_config_id=1,
                        system_name="italian_pizza",
                        point_name="Сухой Лог, Белинского 40",
                        status="resolved",
                        lifecycle_state="resolved",
                        manager_status="accepted",
                        title="resolved",
                        summary_text="resolved",
                        current_items_json=[],
                        last_delta_json={"added": [], "removed": ["Маргарита"], "stayed": []},
                        last_report_hash="resolved-hash",
                        opened_at=now - timedelta(days=5, hours=2),
                        first_seen_at=now - timedelta(days=5, hours=2),
                        last_seen_at=now - timedelta(days=5),
                        resolved_at=now - timedelta(days=5),
                        update_count=2,
                    ),
                    StopListIncident(
                        user_id=user.id,
                        monitor_config_id=1,
                        system_name="italian_pizza",
                        point_name="Сухой Лог, Белинского 40",
                        status="open",
                        lifecycle_state="ongoing",
                        manager_status="accepted",
                        title="open",
                        summary_text="open",
                        current_items_json=["Маргарита"],
                        last_delta_json={"added": ["Маргарита"], "removed": [], "stayed": []},
                        last_report_hash="open-hash",
                        opened_at=now - timedelta(days=2),
                        first_seen_at=now - timedelta(days=2),
                        last_seen_at=now - timedelta(hours=2),
                        update_count=3,
                    ),
                    StopListIncident(
                        user_id=user.id,
                        monitor_config_id=2,
                        system_name="italian_pizza",
                        point_name="Реж, Ленина 17",
                        status="open",
                        lifecycle_state="new",
                        manager_status="needs_help",
                        title="need-help",
                        summary_text="need-help",
                        current_items_json=["Пепперони"],
                        last_delta_json={"added": ["Пепперони"], "removed": [], "stayed": []},
                        last_report_hash="need-help-hash",
                        opened_at=now - timedelta(hours=6),
                        first_seen_at=now - timedelta(hours=6),
                        last_seen_at=now - timedelta(minutes=40),
                        update_count=1,
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_runtime_routes_weekly_stoplist_digest_request(self) -> None:
        decision = self.runtime._rule_based_decision(
            "дай сводку по стоп-листу за неделю",
            AgentSessionSnapshot(user_id=137236883),
            0,
        )

        self.assertEqual(decision.scenario, "stoplist_digest")
        self.assertEqual(decision.selected_tools, ["orchestrator"])
        self.assertEqual(decision.slots.get("period_hint"), "за последнюю неделю")
        self.assertEqual(decision.missing_slots, [])

    def test_digest_snapshot_formats_recurring_and_open_points(self) -> None:
        db = self.SessionLocal()
        try:
            incidents = db.query(StopListIncident).order_by(StopListIncident.id.asc()).all()
        finally:
            db.close()

        snapshot = build_stoplist_digest_snapshot(
            incidents,
            days=7,
            now=datetime(2026, 4, 22, 15, 0, 0),
        )
        text = format_stoplist_digest_text(snapshot)

        self.assertEqual(snapshot.total_incidents, 3)
        self.assertEqual(snapshot.affected_points, 2)
        self.assertEqual(snapshot.open_incidents, 2)
        self.assertEqual(snapshot.recurring_points, 1)
        self.assertEqual(snapshot.need_attention_points, 1)
        self.assertIn("Стоп-лист за последние 7 дней", text)
        self.assertIn("Сухой Лог, Белинского 40 — 2 инцидента", text)
        self.assertIn("реакция: принято", text)
        self.assertIn("Реж, Ленина 17 — 1 инцидент", text)
        self.assertIn("реакция: нужна помощь", text)

    def test_service_chat_returns_stoplist_digest_answer(self) -> None:
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                response = asyncio.run(
                    self.service.chat(
                        DataAgentChatRequest(
                            user_id=137236883,
                            message="дай дайджест по стоп-листу за неделю",
                        )
                    )
                )

        self.assertTrue(response.ok)
        self.assertEqual(response.scenario, "stoplist_digest")
        self.assertIn("Инцидентов: 3", response.answer)
        self.assertIn("Повторялись: 1", response.answer)
        self.assertIn("Нужна реакция: 1", response.answer)

    def test_list_monitors_exposes_open_incident_semantics_for_stoplist(self) -> None:
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            monitors = self.service.list_monitors(137236883)

        by_point = {item.point_name: item for item in monitors}
        dry_log_monitor = by_point["Сухой Лог, Белинского 40"]
        rezh_monitor = by_point["Реж, Ленина 17"]

        self.assertEqual(dry_log_monitor.status_label, "в работе у управляющего")
        self.assertEqual(dry_log_monitor.manager_status_label, "принято")
        self.assertIn("реакция: принято", dry_log_monitor.incident_label or "")

        self.assertEqual(rezh_monitor.status_label, "по кейсу нужна помощь")
        self.assertEqual(rezh_monitor.status_tone, "alert")
        self.assertEqual(rezh_monitor.manager_status_label, "нужна помощь")
        self.assertIn("обновлялся 1 раз", rezh_monitor.incident_label or "")


if __name__ == "__main__":
    unittest.main()
