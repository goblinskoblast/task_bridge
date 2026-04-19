import asyncio
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

from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, DataAgentProfile, DataAgentSystem, User
from data_agent import monitor_scheduler


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)


class _FailFirstBot:
    def __init__(self, failing_chat_id: int) -> None:
        self.failing_chat_id = failing_chat_id
        self.attempts: list[dict] = []
        self.messages: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.attempts.append(kwargs)
        if kwargs.get("chat_id") == self.failing_chat_id:
            raise RuntimeError("primary chat unavailable")
        self.messages.append(kwargs)


class _AlwaysFailBot:
    def __init__(self) -> None:
        self.attempts: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.attempts.append(kwargs)
        raise RuntimeError("telegram unavailable")


class MonitorSchedulerPersistenceTest(unittest.TestCase):
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

        session = self.SessionLocal()
        try:
            user = User(
                telegram_id=555001,
                username="tester",
                first_name="Test",
                last_name=None,
                is_bot=False,
            )
            session.add(user)
            session.flush()

            system = DataAgentSystem(
                user_id=user.id,
                system_name="italian_pizza",
                url="https://tochka.italianpizza.ru/login",
                login="operator",
                encrypted_password="encrypted",
                is_active=True,
            )
            session.add(system)
            session.flush()

            config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="blanks",
                point_name="Сухой Лог, Белинского 40",
                check_interval_minutes=180,
                is_active=True,
            )
            session.add(config)
            session.commit()
            session.refresh(config)
            self.config_id = config.id
            self.detached_config = config
        finally:
            session.close()

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_run_blanks_monitor_persists_status_for_detached_config(self):
        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "🔴 Статус: найдены красные зоны по бланкам\n🔴 Красные зоны:\n🔴 1. Тест",
            "has_red_flags": True,
            "alert_hash": "hash-123",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, self.detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.config_id)
                .all()
            )
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertIsNotNone(config.last_checked_at)
        self.assertEqual(config.last_status, "ok")
        self.assertEqual(config.last_alert_hash, "hash-123")
        self.assertEqual(config.last_result_json.get("report_text"), result["report_text"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "critical")
        self.assertTrue(events[0].sent_to_telegram)
        self.assertEqual(len(bot.messages), 1)
        self.assertIsNone(bot.messages[0].get("parse_mode"))
        self.assertNotIn("<b>", bot.messages[0].get("text", ""))

    def test_run_blanks_monitor_falls_back_to_direct_chat_when_delivery_chat_fails(self):
        primary_chat_id = -100777001
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 555001).first()
            session.add(
                DataAgentProfile(
                    user_id=user.id,
                    blanks_report_chat_id=primary_chat_id,
                    blanks_report_chat_title="Blanks room",
                )
            )
            session.commit()
        finally:
            session.close()

        bot = _FailFirstBot(failing_chat_id=primary_chat_id)
        result = {
            "status": "ok",
            "report_text": "red <unsafe> & still must be delivered",
            "has_red_flags": True,
            "alert_hash": "hash-fallback",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, self.detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertEqual([item.get("chat_id") for item in bot.attempts], [primary_chat_id, 555001])
        self.assertEqual(len(bot.messages), 1)
        self.assertIsNone(bot.messages[0].get("parse_mode"))
        self.assertIn("red <unsafe> & still must be delivered", bot.messages[0].get("text", ""))
        self.assertIsNotNone(config)
        self.assertEqual(config.last_alert_hash, "hash-fallback")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].sent_to_telegram)

    def test_run_blanks_monitor_retries_hashless_red_alert_after_delivery_failure(self):
        failing_bot = _AlwaysFailBot()
        result = {
            "status": "ok",
            "has_red_flags": True,
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                returned = asyncio.run(monitor_scheduler._run_blanks_monitor(failing_bot, self.detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc(), DataAgentMonitorEvent.id.asc())
                .all()
            )
            detached_config = config
        finally:
            session.close()

        self.assertIsNone(returned)
        self.assertEqual(len(failing_bot.attempts), 1)
        self.assertIsNotNone(config)
        self.assertIsNone(config.last_alert_hash)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].sent_to_telegram)
        self.assertTrue(events[0].event_hash)
        self.assertIn("Детали красной зоны", events[0].body)

        successful_bot = _DummyBot()
        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(successful_bot, detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc(), DataAgentMonitorEvent.id.asc())
                .all()
            )
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertTrue(config.last_alert_hash)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[1].sent_to_telegram)
        self.assertEqual(events[0].event_hash, events[1].event_hash)
        self.assertEqual(len(successful_bot.messages), 1)
        self.assertIn("Детали красной зоны", successful_bot.messages[0].get("text", ""))

    def test_run_blanks_monitor_resets_alert_hash_when_red_flags_are_gone(self):
        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            config.last_alert_hash = "hash-123"
            config.last_result_json = {"has_red_flags": True, "alert_hash": "hash-123", "report_text": "old red"}
            session.commit()
            session.refresh(config)
            detached_config = config
        finally:
            session.close()

        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "green",
            "has_red_flags": False,
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertIsNone(config.last_alert_hash)
        self.assertEqual(config.last_result_json.get("report_text"), result["report_text"])
        self.assertEqual(len(events), 0)
        self.assertEqual(len(bot.messages), 0)

    def test_run_blanks_monitor_sends_alert_again_after_clear_with_same_hash(self):
        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            config.last_alert_hash = "hash-123"
            config.last_result_json = {"has_red_flags": False, "report_text": "clear"}
            session.commit()
            session.refresh(config)
            detached_config = config
        finally:
            session.close()

        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "red again",
            "has_red_flags": True,
            "alert_hash": "hash-123",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, detached_config))

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertEqual(config.last_alert_hash, "hash-123")
        self.assertEqual(len(events), 1)
        self.assertEqual(len(bot.messages), 1)

    def test_run_blanks_monitor_does_not_repeat_alert_for_same_active_red_state(self):
        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            config.last_alert_hash = "hash-123"
            config.last_result_json = {"has_red_flags": True, "alert_hash": "hash-123", "report_text": "old red"}
            session.commit()
            session.refresh(config)
            detached_config = config
        finally:
            session.close()

        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "same red",
            "has_red_flags": True,
            "alert_hash": "hash-123",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, detached_config))

        session = self.SessionLocal()
        try:
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertEqual(len(events), 0)
        self.assertEqual(len(bot.messages), 0)

    def test_run_blanks_monitor_failure_stays_internal(self):
        bot = _DummyBot()
        result = {
            "status": "failed",
            "message": "Login failed",
            "diagnostics": {"stage": "login_submit"},
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, self.detached_config))

        session = self.SessionLocal()
        try:
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc())
                .all()
            )
        finally:
            session.close()

        self.assertEqual(len(bot.messages), 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "error")
        self.assertFalse(events[0].sent_to_telegram)

    def test_run_blanks_monitor_failure_preserves_existing_sent_event(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 555001).first()
            session.add(
                DataAgentMonitorEvent(
                    user_id=user.id,
                    config_id=self.config_id,
                    system_name="italian_pizza",
                    monitor_type="blanks",
                    point_name="РЎСѓС…РѕР№ Р›РѕРі, Р‘РµР»РёРЅСЃРєРѕРіРѕ 40",
                    severity="error",
                    title="РњРѕРЅРёС‚РѕСЂРёРЅРі Р·Р°РІРµСЂС€РёР»СЃСЏ СЃ РѕС€РёР±РєРѕР№",
                    body="old failure",
                    event_hash="old-failure",
                    sent_to_telegram=True,
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()
        finally:
            session.close()

        bot = _DummyBot()
        result = {
            "status": "failed",
            "message": "Login failed again",
            "diagnostics": {"stage": "login_submit"},
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(monitor_scheduler._run_blanks_monitor(bot, self.detached_config))

        session = self.SessionLocal()
        try:
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc())
                .all()
            )
        finally:
            session.close()

        self.assertEqual(len(bot.messages), 0)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0].sent_to_telegram)
        self.assertFalse(events[1].sent_to_telegram)

    def test_probe_blanks_monitor_failure_does_not_write_or_notify(self):
        bot = _DummyBot()
        result = {
            "status": "failed",
            "message": "probe failure",
            "diagnostics": {"stage": "login_submit"},
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                returned = asyncio.run(
                    monitor_scheduler._run_blanks_monitor(
                        bot,
                        self.detached_config,
                        notify_user=False,
                        persist_state=False,
                    )
                )

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertEqual(returned, result)
        self.assertIsNotNone(config)
        self.assertIsNone(config.last_checked_at)
        self.assertIsNone(config.last_status)
        self.assertIsNone(config.last_result_json)
        self.assertIsNone(config.last_alert_hash)
        self.assertEqual(len(events), 0)
        self.assertEqual(len(bot.messages), 0)

    def test_probe_blanks_monitor_red_result_does_not_write_or_notify(self):
        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "red probe",
            "has_red_flags": True,
            "alert_hash": "probe-red-hash",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.blanks_tool,
                "inspect_point",
                new=AsyncMock(return_value=result),
            ):
                returned = asyncio.run(
                    monitor_scheduler._run_blanks_monitor(
                        bot,
                        self.detached_config,
                        notify_user=False,
                        persist_state=False,
                    )
                )

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == self.config_id).first()
            events = session.query(DataAgentMonitorEvent).filter(DataAgentMonitorEvent.config_id == self.config_id).all()
        finally:
            session.close()

        self.assertEqual(returned, result)
        self.assertIsNotNone(config)
        self.assertIsNone(config.last_checked_at)
        self.assertIsNone(config.last_status)
        self.assertIsNone(config.last_result_json)
        self.assertIsNone(config.last_alert_hash)
        self.assertEqual(len(events), 0)
        self.assertEqual(len(bot.messages), 0)

    def test_run_reviews_monitor_persists_hash_even_without_delivery(self):
        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.telegram_id == 555001).first()
            review_config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="reviews",
                point_name="Все точки",
                check_interval_minutes=1440,
                is_active=True,
            )
            session.add(review_config)
            session.commit()
            session.refresh(review_config)
            detached_review_config = review_config
            review_config_id = review_config.id
        finally:
            session.close()

        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "Отзывы обновились",
            "alert_hash": "review-hash-1",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.review_report_service,
                "build_report_for_window_label",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(
                    monitor_scheduler._run_reviews_monitor(
                        bot,
                        detached_review_config,
                        notify_user=False,
                    )
                )

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == review_config_id).first()
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == review_config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc(), DataAgentMonitorEvent.id.asc())
                .all()
            )
            detached_review_config = config
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertEqual(config.last_alert_hash, "review-hash-1")
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].sent_to_telegram)
        self.assertEqual(len(bot.messages), 0)

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.review_report_service,
                "build_report_for_window_label",
                new=AsyncMock(return_value=result),
            ):
                asyncio.run(
                    monitor_scheduler._run_reviews_monitor(
                        bot,
                        detached_review_config,
                        notify_user=False,
                    )
                )

        session = self.SessionLocal()
        try:
            config = session.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == review_config_id).first()
            events = (
                session.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == review_config_id)
                .order_by(DataAgentMonitorEvent.created_at.asc(), DataAgentMonitorEvent.id.asc())
                .all()
            )
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertEqual(config.last_alert_hash, "review-hash-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(len(bot.messages), 0)


if __name__ == "__main__":
    unittest.main()
