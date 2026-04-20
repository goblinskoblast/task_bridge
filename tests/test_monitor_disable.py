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

    async def test_chat_disables_single_monitor_by_point_without_monitor_id(self):
        decision = AgentDecision(
            scenario="monitor_management",
            selected_tools=["orchestrator"],
            slots={
                "point_name": self.point_name,
                "monitor_action": "disable",
                "source_message": "останови мониторинг",
            },
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
                                message="Останови мониторинг по Сухой Лог Белинского 40.",
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
        self.assertEqual(response.scenario, "monitor_management")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.answer, f"Отключил мониторинг бланков по точке {self.point_name}.")
        self.assertIsNotNone(config)
        self.assertFalse(config.is_active)

    async def test_chat_disables_all_monitor_types_by_point_when_explicit(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
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

        decision = AgentDecision(
            scenario="monitor_management",
            selected_tools=["orchestrator"],
            slots={
                "point_name": self.point_name,
                "monitor_action": "disable",
                "all_monitor_types": True,
                "source_message": "выключи все мониторинги",
            },
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
                                message="Выключи все мониторинги по Сухой Лог Белинского 40.",
                            )
                        )

        session = self.SessionLocal()
        try:
            active_count = (
                session.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.point_name == self.point_name,
                    DataAgentMonitorConfig.is_active == True,
                )
                .count()
            )
        finally:
            session.close()

        mocked_execute.assert_not_awaited()
        self.assertTrue(response.ok)
        self.assertEqual(active_count, 0)
        self.assertEqual(response.answer, f"Отключил все мониторинги по точке {self.point_name}.")

    async def test_chat_disables_all_blanks_without_point_when_type_scope_is_explicit(self):
        other_point = "Реж, Ленина 17"
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=other_point,
                    check_interval_minutes=180,
                    is_active=True,
                    active_from_hour=8,
                    active_to_hour=20,
                )
            )
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
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

        decision = AgentDecision(
            scenario="blanks_report",
            selected_tools=["blanks_tool"],
            slots={
                "monitor_action": "disable",
                "all_points": True,
                "source_message": "выключи все бланки",
            },
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
                                message="Выключи все бланки.",
                            )
                        )

        session = self.SessionLocal()
        try:
            active_blanks_count = (
                session.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.monitor_type == "blanks",
                    DataAgentMonitorConfig.is_active == True,
                )
                .count()
            )
            active_stoplist_count = (
                session.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.monitor_type == "stoplist",
                    DataAgentMonitorConfig.is_active == True,
                )
                .count()
            )
        finally:
            session.close()

        mocked_execute.assert_not_awaited()
        self.assertTrue(response.ok)
        self.assertEqual(active_blanks_count, 0)
        self.assertEqual(active_stoplist_count, 1)
        self.assertEqual(response.answer, "Отключил все мониторинги бланков.")

    async def test_chat_updates_monitor_window_without_running_report(self):
        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.point_name == self.point_name).first()
            config.check_interval_minutes = 120
            session.commit()
        finally:
            session.close()

        decision = AgentDecision(
            scenario="blanks_report",
            selected_tools=["blanks_tool"],
            slots={
                "point_name": self.point_name,
                "monitor_action": "update",
                "monitor_interval_minutes": 180,
                "monitor_interval_source": "default_intent",
                "monitor_start_hour": 11,
                "monitor_end_hour": 21,
                "source_message": "измени окно мониторинга",
            },
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
                                message="Измени окно мониторинга бланков по Сухой Лог Белинского 40 с 11 до 21.",
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
        self.assertIsNotNone(config)
        self.assertEqual(config.check_interval_minutes, 120)
        self.assertEqual(config.active_from_hour, 9)
        self.assertEqual(config.active_to_hour, 19)
        self.assertIn("Обновил", response.answer)
        self.assertIn("каждые 2 ч.", response.answer)

    async def test_chat_updates_single_monitor_by_point_without_type(self):
        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.point_name == self.point_name).first()
            config.check_interval_minutes = 120
            session.commit()
        finally:
            session.close()

        decision = AgentDecision(
            scenario="monitor_management",
            selected_tools=["orchestrator"],
            slots={
                "point_name": self.point_name,
                "monitor_action": "update",
                "monitor_start_hour": 11,
                "monitor_end_hour": 21,
                "source_message": "поменяй время мониторинга",
            },
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
                                message="Поменяй время мониторинга по Сухой Лог Белинского 40 с 11 до 21.",
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
        self.assertEqual(response.scenario, "monitor_management")
        self.assertIsNotNone(config)
        self.assertEqual(config.monitor_type, "blanks")
        self.assertEqual(config.check_interval_minutes, 120)
        self.assertEqual(config.active_from_hour, 9)
        self.assertEqual(config.active_to_hour, 19)
        self.assertIn("Обновил", response.answer)
        self.assertIn("бланков", response.answer)

    def test_update_monitor_by_point_asks_type_when_multiple_monitors_are_active(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
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

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._update_monitor_settings(
                user_id=137236883,
                scenario="monitor_management",
                point_name=self.point_name,
                interval_minutes=None,
                start_hour=11,
                end_hour=21,
            )

        self.assertIn("включено несколько мониторингов", answer)
        self.assertIn("бланки", answer)
        self.assertIn("стоп-лист", answer)
        self.assertIn("измени окно бланков", answer)
        self.assertNotIn("ID", answer)

    def test_disable_monitor_by_point_asks_type_when_multiple_monitors_are_active(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            session.add(
                DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
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

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._disable_monitor(
                user_id=137236883,
                scenario="monitor_management",
                point_name=self.point_name,
            )

        session = self.SessionLocal()
        try:
            active_count = (
                session.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.point_name == self.point_name,
                    DataAgentMonitorConfig.is_active == True,
                )
                .count()
            )
        finally:
            session.close()

        self.assertEqual(active_count, 2)
        self.assertIn("включено несколько мониторингов", answer)
        self.assertIn("бланки", answer)
        self.assertIn("стоп-лист", answer)
        self.assertIn("не присылай бланки", answer)
        self.assertNotIn("ID", answer)

    def test_build_monitors_summary_uses_user_timezone_and_plain_text(self):
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._build_monitors_summary(137236883)
        self.assertIn("\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430:", answer)

        self.assertIn("Активные мониторинги:", answer)
        self.assertIn(f"Бланки: {self.point_name}", answer)
        self.assertIn("каждые 3 часа", answer)
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", answer)
        self.assertIn("Последняя проверка: ещё не было", answer)
        self.assertIn("Что придёт: сразу сообщу, если появится красная зона", answer)
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
        self.assertEqual(monitors[0].behavior_label, "сразу сообщу, если появится красная зона")

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
        self.assertIn("Что придёт: сразу сообщу, если появится красная зона", answer)
        self.assertIn("Последнее уведомление: 14.04 в 13:02, была красная зона", answer)
        self.assertIn("Отправка: чат «Бланки priority»", answer)
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0].last_checked_label, "сегодня в 18:10")
        self.assertEqual(monitors[0].last_event_label, "14.04 в 13:02, была красная зона")
        self.assertEqual(monitors[0].delivery_label, "чат «Бланки priority»")
        self.assertEqual(monitors[0].behavior_label, "сразу сообщу, если появится красная зона")

        self.assertEqual(monitors[0].next_check_label, "\u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0432 22:00")

    def test_monitor_summary_hides_corrupted_delivery_chat_title(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            session.add(
                DataAgentProfile(
                    user_id=user.id,
                    blanks_report_chat_id=900001,
                    blanks_report_chat_title="????????",
                )
            )
            session.commit()
        finally:
            session.close()

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            answer = self.service._build_monitors_summary(137236883)
            monitors = self.service.list_monitors(137236883)

        self.assertIn("Отправка: привязанный чат", answer)
        self.assertNotIn("????", answer)
        self.assertEqual(monitors[0].delivery_label, "привязанный чат")

    def test_monitor_summaries_distinguish_unsent_stoplist_event_from_notification(self):
        stoplist_point = "Сухой Лог, Белинского 40 stoplist"
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="stoplist",
                point_name=stoplist_point,
                check_interval_minutes=180,
                is_active=True,
                active_from_hour=8,
                active_to_hour=20,
                last_status="ok",
                last_checked_at=datetime(2026, 4, 15, 13, 10, 4),
                last_result_json={"report_text": "stoplist", "status": "ok"},
            )
            session.add(config)
            session.flush()
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
                    point_name=stoplist_point,
                    severity="info",
                    title="Стоп-лист по расписанию",
                    body="report",
                    event_hash="stoplist-1",
                    sent_to_telegram=False,
                    created_at=datetime(2026, 4, 14, 8, 2, 32),
                )
            )
            session.commit()
        finally:
            session.close()

        def _format_moment(value):
            if value == datetime(2026, 4, 15, 13, 10, 4):
                return "сегодня в 18:10"
            if value == datetime(2026, 4, 14, 8, 2, 32):
                return "14.04 в 13:02"
            return "пока не было"

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.format_monitor_moment", side_effect=_format_moment):
                with patch("data_agent.service.format_monitor_next_check", return_value="сегодня в 22:00"):
                    answer = self.service._build_monitors_summary(137236883)
                    monitors = self.service.list_monitors(137236883)

        stoplist_monitor = next(item for item in monitors if item.monitor_type == "stoplist")
        self.assertIn("Последнее событие: 14.04 в 13:02, отчёт сформирован", answer)
        self.assertEqual(stoplist_monitor.last_event_title, "Последнее событие")
        self.assertEqual(stoplist_monitor.last_event_label, "14.04 в 13:02, отчёт сформирован")

    def test_monitor_summaries_use_latest_stoplist_event_even_if_older_one_was_sent(self):
        stoplist_point = "Сухой Лог, Белинского 40 latest stoplist"
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="stoplist",
                point_name=stoplist_point,
                check_interval_minutes=180,
                is_active=True,
                active_from_hour=8,
                active_to_hour=20,
                last_status="ok",
                last_checked_at=datetime(2026, 4, 15, 13, 10, 4),
                last_result_json={"report_text": "stoplist", "status": "ok"},
            )
            session.add(config)
            session.flush()
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
                    point_name=stoplist_point,
                    severity="info",
                    title="Стоп-лист был отправлен",
                    body="old report",
                    event_hash="stoplist-old",
                    sent_to_telegram=True,
                    created_at=datetime(2026, 4, 14, 8, 2, 32),
                )
            )
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="stoplist",
                    point_name=stoplist_point,
                    severity="info",
                    title="Стоп-лист обновился",
                    body="new report",
                    event_hash="stoplist-new",
                    sent_to_telegram=False,
                    created_at=datetime(2026, 4, 15, 9, 4, 10),
                )
            )
            session.commit()
        finally:
            session.close()

        def _format_moment(value):
            if value == datetime(2026, 4, 15, 13, 10, 4):
                return "сегодня в 18:10"
            if value == datetime(2026, 4, 15, 9, 4, 10):
                return "15.04 в 14:04"
            if value == datetime(2026, 4, 14, 8, 2, 32):
                return "14.04 в 13:02"
            return "пока не было"

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.format_monitor_moment", side_effect=_format_moment):
                with patch("data_agent.service.format_monitor_next_check", return_value="сегодня в 22:00"):
                    answer = self.service._build_monitors_summary(137236883)
                    monitors = self.service.list_monitors(137236883)

        stoplist_monitor = next(item for item in monitors if item.point_name == stoplist_point)
        self.assertIn("Последнее событие: 15.04 в 14:04, отчёт сформирован", answer)
        self.assertEqual(stoplist_monitor.last_event_title, "Последнее событие")
        self.assertEqual(stoplist_monitor.last_event_label, "15.04 в 14:04, отчёт сформирован")

    def test_monitor_summaries_show_latest_internal_failure_without_technical_details(self):
        blanks_point = "Сухой Лог, Белинского 40 latest failure"
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="blanks",
                point_name=blanks_point,
                check_interval_minutes=180,
                is_active=True,
                active_from_hour=8,
                active_to_hour=20,
                last_status="failed",
                last_checked_at=datetime(2026, 4, 15, 13, 10, 4),
                last_result_json={"status": "failed", "message": "Login failed"},
            )
            session.add(config)
            session.flush()
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=blanks_point,
                    severity="critical",
                    title="Найдены красные бланки",
                    body="red",
                    event_hash="critical-old",
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
                    point_name=blanks_point,
                    severity="error",
                    title="Мониторинг завершился с ошибкой",
                    body="Trace: internal\nЭтап: login_submit",
                    event_hash="error-new",
                    sent_to_telegram=False,
                    created_at=datetime(2026, 4, 15, 9, 4, 10),
                )
            )
            session.commit()
        finally:
            session.close()

        def _format_moment(value):
            if value == datetime(2026, 4, 15, 13, 10, 4):
                return "сегодня в 18:10"
            if value == datetime(2026, 4, 15, 9, 4, 10):
                return "15.04 в 14:04"
            if value == datetime(2026, 4, 14, 8, 2, 32):
                return "14.04 в 13:02"
            return "пока не было"

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.format_monitor_moment", side_effect=_format_moment):
                with patch("data_agent.service.format_monitor_next_check", return_value="сегодня в 22:00"):
                    answer = self.service._build_monitors_summary(137236883)
                    monitors = self.service.list_monitors(137236883)

        blanks_monitor = next(item for item in monitors if item.point_name == blanks_point)
        self.assertIn("Сейчас: нужна повторная проверка", answer)
        self.assertIn("Последнее событие: 15.04 в 14:04, проверка не завершилась, повторим автоматически", answer)
        self.assertNotIn("login_submit", answer)
        self.assertNotIn("Trace:", answer)
        self.assertEqual(blanks_monitor.last_event_title, "Последнее событие")
        self.assertEqual(
            blanks_monitor.last_event_label,
            "15.04 в 14:04, проверка не завершилась, повторим автоматически",
        )

    def test_monitor_summaries_show_needs_period_as_retry_needed(self):
        blanks_point = "Сухой Лог, Белинского 40 needs period"
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 137236883).first()
            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="blanks",
                point_name=blanks_point,
                check_interval_minutes=180,
                is_active=True,
                active_from_hour=8,
                active_to_hour=20,
                last_status="needs_period",
                last_checked_at=datetime(2026, 4, 15, 13, 10, 4),
                last_result_json={"status": "needs_period", "message": "Choose period"},
            )
            session.add(config)
            session.flush()
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=config.id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name=blanks_point,
                    severity="error",
                    title="Мониторинг завершился с ошибкой",
                    body="Trace: internal\nЭтап: period_selection",
                    event_hash="needs-period",
                    sent_to_telegram=False,
                    created_at=datetime(2026, 4, 15, 9, 4, 10),
                )
            )
            session.commit()
        finally:
            session.close()

        def _format_moment(value):
            if value == datetime(2026, 4, 15, 13, 10, 4):
                return "сегодня в 18:10"
            if value == datetime(2026, 4, 15, 9, 4, 10):
                return "15.04 в 14:04"
            return "пока не было"

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.format_monitor_moment", side_effect=_format_moment):
                with patch("data_agent.service.format_monitor_next_check", return_value="сегодня в 22:00"):
                    answer = self.service._build_monitors_summary(137236883)

        self.assertIn("Сейчас: нужна повторная проверка", answer)
        self.assertIn("Последнее событие: 15.04 в 14:04, проверка не завершилась, повторим автоматически", answer)
        self.assertNotIn("period_selection", answer)
        self.assertNotIn("Trace:", answer)

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
