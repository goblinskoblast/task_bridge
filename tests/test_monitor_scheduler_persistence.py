import asyncio
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

from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, DataAgentSystem, User
from data_agent import monitor_scheduler


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)


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
        self.assertTrue(events[0].sent_to_telegram)
        self.assertEqual(len(bot.messages), 1)


if __name__ == "__main__":
    unittest.main()
