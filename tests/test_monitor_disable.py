import os
import tempfile
import unittest
from datetime import datetime
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
from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, DataAgentProfile, User


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
        self.assertIn("\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430:", answer)

        self.assertIn("Активные мониторинги:", answer)
        self.assertIn(f"Бланки: {self.point_name}", answer)
        self.assertIn("каждые 3 часа", answer)
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", answer)
        self.assertIn("Последняя проверка: ещё не было", answer)
        self.assertIn("Последнее уведомление: пока не было", answer)
        self.assertNotIn("/unmonitor", answer)

    def test_build_monitors_summary_marks_red_blanks_as_active_alert(self):
        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == self.point_name)
                .first()
            )
            config.last_status = "ok"
            config.last_result_json = {"has_red_flags": True, "report_text": "red"}
            session.commit()
        finally:
            session.close()

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._build_monitors_summary(137236883)

        self.assertIn("есть красная зона", answer)

    def test_list_monitors_returns_user_facing_status_fields(self):
        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == self.point_name)
                .first()
            )
            config.last_status = "ok"
            config.last_result_json = {"has_red_flags": True, "report_text": "red"}
            session.commit()
        finally:
            session.close()

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            monitors = self.service.list_monitors(137236883)
        self.assertTrue(bool(monitors[0].next_check_label))

        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0].status_label, "есть красная зона")
        self.assertTrue(monitors[0].has_active_alert)
        self.assertTrue(bool(monitors[0].interval_label))
        self.assertTrue(bool(monitors[0].window_label))

    def test_monitor_summaries_include_delivery_and_latest_user_facing_event(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == self.point_name)
                .first()
            )
            session.add(
                DataAgentProfile(
                    user_id=user.id,
                    blanks_report_chat_id=900001,
                    blanks_report_chat_title="Бланки priority",
                )
            )
            config.last_status = "ok"
            config.last_checked_at = datetime(2026, 4, 15, 13, 10, 4)
            config.last_result_json = {"has_red_flags": False, "report_text": "green"}
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=self.point_name,
                    severity="critical",
                    title="Найдены красные бланки",
                    body="red",
                    event_hash="critical-1",
                    sent_to_telegram=True,
                    created_at=datetime(2026, 4, 14, 8, 2, 32),
                )
            )
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=self.point_name,
                    severity="error",
                    title="Мониторинг завершился с ошибкой",
                    body="error",
                    event_hash="error-1",
                    sent_to_telegram=False,
                    created_at=datetime(2026, 4, 15, 12, 58, 54),
                )
            )
            session.commit()
        finally:
            session.close()

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch(
                "data_agent.service.format_monitor_moment",
                side_effect=["сегодня в 18:10", "14.04 в 13:02"],
            ):
                with patch(
                    "data_agent.service.format_monitor_next_check",
                    return_value="\u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0432 22:00",
                ):
                    answer = self.service._build_monitors_summary(137236883)

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch(
                "data_agent.service.format_monitor_moment",
                side_effect=["сегодня в 18:10", "14.04 в 13:02"],
            ):
                with patch(
                    "data_agent.service.format_monitor_next_check",
                    return_value="\u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0432 22:00",
                ):
                    monitors = self.service.list_monitors(137236883)

        self.assertIn("Последняя проверка: сегодня в 18:10", answer)
        self.assertIn("Последнее уведомление: 14.04 в 13:02, была красная зона", answer)
        self.assertIn("Отправка: чат «Бланки priority»", answer)
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0].last_checked_label, "сегодня в 18:10")
        self.assertEqual(monitors[0].last_event_label, "14.04 в 13:02, была красная зона")
        self.assertEqual(monitors[0].delivery_label, "чат «Бланки priority»")

        self.assertEqual(monitors[0].next_check_label, "\u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0432 22:00")

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
