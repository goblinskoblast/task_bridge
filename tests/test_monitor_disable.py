import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent.agent_runtime import AgentDecision
from data_agent.models import DataAgentChatRequest
from data_agent.service import DataAgentService
from db.models import Base, DataAgentMonitorConfig, User


class MonitorDisableTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = Path(path)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.service = DataAgentService()
        self.point_name = "Сухой Лог, Белинского 40"

        session = self.SessionLocal()
        try:
            user = User(
                telegram_id=137236883,
                username="priority",
                first_name="Priority",
                last_name=None,
                is_bot=False,
            )
            session.add(user)
            session.flush()
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=self.point_name,
                    check_interval_minutes=180,
                    is_active=True,
                    active_from_hour=8,
                    active_to_hour=20,
                )
            )
            session.commit()
        finally:
            session.close()

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_disable_monitor_marks_existing_config_inactive(self):
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._disable_monitor(
                user_id=137236883,
                scenario="blanks_report",
                point_name=self.point_name,
            )

        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == self.point_name)
                .first()
            )
        finally:
            session.close()

        self.assertEqual(answer, f"Отключил мониторинг бланков по точке {self.point_name}.")
        self.assertIsNotNone(config)
        self.assertFalse(config.is_active)

    async def test_chat_short_circuits_disable_action_without_running_scenario_engine(self):
        decision = AgentDecision(
            scenario="blanks_report",
            selected_tools=["blanks_tool"],
            slots={"point_name": self.point_name, "monitor_action": "disable", "source_message": "не присылай"},
            missing_slots=[],
            reasoning="test",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                with patch("data_agent.service.agent_runtime.decide", AsyncMock(return_value=decision)):
                    with patch("data_agent.service.scenario_engine.execute", AsyncMock()) as mocked_execute:
                        response = await self.service.chat(
                            DataAgentChatRequest(
                                user_id=137236883,
                                message="Не присылай мне бланки по Сухой Лог Белинского 40.",
                            )
                        )

        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == self.point_name)
                .first()
            )
        finally:
            session.close()

        mocked_execute.assert_not_awaited()
        self.assertTrue(response.ok)
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.answer, f"Отключил мониторинг бланков по точке {self.point_name}.")
        self.assertIsNotNone(config)
        self.assertFalse(config.is_active)

    def test_build_monitors_summary_uses_user_timezone_and_plain_text(self):
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._build_monitors_summary(137236883)

        self.assertIn("Активные мониторинги:", answer)
        self.assertIn(f"Бланки: {self.point_name}", answer)
        self.assertIn("каждые 3 часа", answer)
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", answer)
        self.assertIn("Последняя проверка: ещё не было.", answer)
        self.assertNotIn("/unmonitor", answer)

    async def test_chat_short_circuits_monitor_list_without_running_scenario_engine(self):
        decision = AgentDecision(
            scenario="monitor_management",
            selected_tools=["orchestrator"],
            slots={"monitor_action": "list", "source_message": "покажи мониторинги"},
            missing_slots=[],
            reasoning="test",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                with patch("data_agent.service.agent_runtime.decide", AsyncMock(return_value=decision)):
                    with patch("data_agent.service.scenario_engine.execute", AsyncMock()) as mocked_execute:
                        response = await self.service.chat(
                            DataAgentChatRequest(
                                user_id=137236883,
                                message="Покажи мои активные мониторинги.",
                            )
                        )

        mocked_execute.assert_not_awaited()
        self.assertTrue(response.ok)
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.scenario, "monitor_management")
        self.assertIn("Активные мониторинги:", response.answer)
        self.assertIn(self.point_name, response.answer)

    async def test_chat_failure_response_is_neutral_without_internal_error(self):
        fallback_decision = AgentDecision(
            scenario="general",
            selected_tools=["orchestrator"],
            slots={"source_message": "покажи мониторинги"},
            missing_slots=[],
            reasoning="fallback",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.agent_runtime.get_db_session", side_effect=self.SessionLocal):
                with patch("data_agent.service.logger.exception"):
                    with patch("data_agent.service.agent_runtime.decide", AsyncMock(side_effect=RuntimeError("Page.evaluate failed"))):
                        with patch("data_agent.service.agent_runtime.decide_fast", return_value=fallback_decision):
                            response = await self.service.chat(
                                DataAgentChatRequest(
                                    user_id=137236883,
                                    message="Покажи мои активные мониторинги.",
                                )
                            )

        self.assertFalse(response.ok)
        self.assertEqual(response.answer, "Не удалось выполнить запрос. Попробуйте повторить чуть позже.")
        self.assertNotIn("Page.evaluate", response.answer)
        self.assertNotIn("failed", response.answer.lower())


if __name__ == "__main__":
    unittest.main()
