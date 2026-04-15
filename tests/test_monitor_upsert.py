import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from db.models import Base, DataAgentMonitorConfig, User
from data_agent.service import DataAgentService


class MonitorUpsertTest(unittest.TestCase):
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
            session.commit()
        finally:
            session.close()

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_upsert_monitor_applies_default_business_window_for_new_monitor(self):
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            note = self.service._upsert_monitor(
                user_id=137236883,
                scenario="blanks_report",
                point_name="Сухой Лог, Белинского 40",
                interval_minutes=180,
            )

        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == "Сухой Лог, Белинского 40")
                .first()
            )
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertEqual(config.active_from_hour, 8)
        self.assertEqual(config.active_to_hour, 20)
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", note or "")

    def test_upsert_monitor_converts_explicit_window_to_service_timezone(self):
        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            note = self.service._upsert_monitor(
                user_id=137236883,
                scenario="stoplist_report",
                point_name="Сухой Лог, Белинского 40",
                interval_minutes=180,
                start_hour=11,
                end_hour=21,
            )

        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(DataAgentMonitorConfig.point_name == "Сухой Лог, Белинского 40")
                .first()
            )
        finally:
            session.close()

        self.assertIsNotNone(config)
        self.assertEqual(config.active_from_hour, 9)
        self.assertEqual(config.active_to_hour, 19)
        self.assertIn("с 11:00 до 21:00 по Екатеринбургу", note or "")


if __name__ == "__main__":
    unittest.main()
