import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data_agent.agent_runtime import AgentDecision, AgentSessionSnapshot, DataAgentRuntime
from data_agent.models import DataAgentChatRequest
from data_agent.service import DataAgentService
from db.models import Base, DataAgentMonitorConfig, StopListIncident, User


class StopListSkillTest(unittest.TestCase):
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

            now = datetime(2026, 4, 23, 12, 0, 0)
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
                        status="open",
                        lifecycle_state="ongoing",
                        manager_status="accepted",
                        title="ongoing",
                        summary_text="ongoing",
                        current_items_json=["Маргарита"],
                        last_delta_json={"added": ["Маргарита"], "removed": [], "stayed": []},
                        last_report_hash="open-hash",
                        opened_at=now - timedelta(days=2),
                        first_seen_at=now - timedelta(days=2),
                        last_seen_at=now - timedelta(hours=3),
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

    def test_override_switches_meta_stoplist_question_to_skill(self) -> None:
        base_decision = AgentDecision(
            scenario="stoplist_report",
            selected_tools=["stoplist_tool"],
            slots={"source_message": "что по стоп-листу сейчас"},
            missing_slots=["point_name"],
            reasoning="base",
        )

        overridden = self.service._maybe_override_stoplist_skill(
            base_decision,
            "что по стоп-листу сейчас",
        )

        self.assertEqual(overridden.scenario, "stoplist_skill")
        self.assertEqual(overridden.selected_tools, ["orchestrator"])
        self.assertEqual(overridden.missing_slots, [])
        self.assertEqual(overridden.slots.get("stoplist_skill_focus"), "overview")

    def test_override_keeps_raw_stoplist_report_request_as_report(self) -> None:
        base_decision = self.runtime._rule_based_decision(
            "покажи стоп-лист по Сухой Лог, Белинского 40",
            AgentSessionSnapshot(user_id=137236883),
            0,
        )

        overridden = self.service._maybe_override_stoplist_skill(
            base_decision,
            "покажи стоп-лист по Сухой Лог, Белинского 40",
        )

        self.assertEqual(base_decision.scenario, "stoplist_report")
        self.assertEqual(overridden.scenario, "stoplist_report")

    def test_service_chat_returns_attention_view_for_stoplist_skill(self) -> None:
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                response = asyncio.run(
                    self.service.chat(
                        DataAgentChatRequest(
                            user_id=137236883,
                            message="какие кейсы по стоп-листу требуют реакции",
                        )
                    )
                )

        self.assertTrue(response.ok)
        self.assertEqual(response.scenario, "stoplist_skill")
        self.assertIn("требуют реакции 1 кейс", response.answer)
        self.assertIn("Реж, Ленина 17", response.answer)

    def test_service_chat_returns_point_status_view_for_stoplist_skill(self) -> None:
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                response = asyncio.run(
                    self.service.chat(
                        DataAgentChatRequest(
                            user_id=137236883,
                            message="какой статус кейса по стоп-листу по Сухой Лог, Белинского 40",
                        )
                    )
                )

        self.assertTrue(response.ok)
        self.assertEqual(response.scenario, "stoplist_skill")
        self.assertIn("По точке Сухой Лог, Белинского 40", response.answer)
        self.assertIn("в работе у управляющего", response.answer)
        self.assertIn("Реакция: принято", response.answer)


if __name__ == "__main__":
    unittest.main()
