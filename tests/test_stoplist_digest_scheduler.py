import asyncio
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from db.models import (
    Base,
    DataAgentMonitorConfig,
    DataAgentProfile,
    StopListIncident,
    StopListWeeklyDigestDelivery,
    User,
)
from data_agent import stoplist_digest_scheduler


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self._next_message_id = 9000

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        self._next_message_id += 1
        return SimpleNamespace(
            message_id=self._next_message_id,
            date=datetime(2026, 4, 27, 11, 5, 0),
        )


class StopListDigestSchedulerTest(unittest.TestCase):
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
            priority_user = User(
                telegram_id=137236883,
                username="priority",
                first_name="Priority",
                last_name=None,
                is_bot=False,
            )
            direct_user = User(
                telegram_id=5550002,
                username="direct",
                first_name="Direct",
                last_name=None,
                is_bot=False,
            )
            db.add_all([priority_user, direct_user])
            db.flush()

            db.add(
                DataAgentProfile(
                    user_id=priority_user.id,
                    stoplist_report_chat_id=-100123456,
                    stoplist_report_chat_title="Stoplist HQ",
                )
            )
            db.add_all(
                [
                    DataAgentMonitorConfig(
                        user_id=priority_user.id,
                        system_name="italian_pizza",
                        monitor_type="stoplist",
                        point_name="Сухой Лог, Белинского 40",
                        check_interval_minutes=180,
                        is_active=True,
                    ),
                    DataAgentMonitorConfig(
                        user_id=direct_user.id,
                        system_name="italian_pizza",
                        monitor_type="stoplist",
                        point_name="Реж, Ленина 17",
                        check_interval_minutes=180,
                        is_active=True,
                    ),
                ]
            )
            db.flush()

            now = datetime(2026, 4, 27, 11, 5, 0)
            db.add_all(
                [
                    StopListIncident(
                        user_id=priority_user.id,
                        monitor_config_id=1,
                        system_name="italian_pizza",
                        point_name="Сухой Лог, Белинского 40",
                        status="open",
                        lifecycle_state="ongoing",
                        manager_status="accepted",
                        title="open",
                        summary_text="open",
                        current_items_json=["Пепперони"],
                        last_delta_json={"added": ["Пепперони"], "removed": [], "stayed": []},
                        last_report_hash="hash-1",
                        opened_at=now - timedelta(days=2),
                        first_seen_at=now - timedelta(days=2),
                        last_seen_at=now - timedelta(hours=3),
                        update_count=2,
                    ),
                    StopListIncident(
                        user_id=priority_user.id,
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
                        last_report_hash="hash-2",
                        opened_at=now - timedelta(days=5),
                        first_seen_at=now - timedelta(days=5),
                        last_seen_at=now - timedelta(days=4, hours=20),
                        resolved_at=now - timedelta(days=4, hours=20),
                        update_count=1,
                    ),
                    StopListIncident(
                        user_id=direct_user.id,
                        monitor_config_id=2,
                        system_name="italian_pizza",
                        point_name="Реж, Ленина 17",
                        status="open",
                        lifecycle_state="new",
                        manager_status="needs_help",
                        title="need-help",
                        summary_text="need-help",
                        current_items_json=["Сырная"],
                        last_delta_json={"added": ["Сырная"], "removed": [], "stayed": []},
                        last_report_hash="hash-3",
                        opened_at=now - timedelta(hours=10),
                        first_seen_at=now - timedelta(hours=10),
                        last_seen_at=now - timedelta(hours=1),
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

    def test_due_candidates_use_stoplist_report_chat(self) -> None:
        db = self.SessionLocal()
        try:
            candidates = stoplist_digest_scheduler._build_due_stoplist_weekly_digest_candidates(
                db,
                now_local=datetime(2026, 4, 27, 11, 5, 0),
                lookback_days=7,
            )
        finally:
            db.close()

        by_user = {item.telegram_user_id: item for item in candidates}
        priority_candidate = by_user[137236883]

        self.assertEqual(priority_candidate.chat_id, -100123456)
        self.assertEqual(priority_candidate.chat_title, "Stoplist HQ")
        self.assertEqual(priority_candidate.delivery_target, "profile_stoplist_chat")
        self.assertIn("Еженедельный дайджест по стоп-листу", priority_candidate.text)
        self.assertIn("Сухой Лог, Белинского 40", priority_candidate.text)
        self.assertEqual(priority_candidate.incidents_count, 2)

    def test_send_due_stoplist_weekly_digests_records_delivery_and_skips_duplicates(self) -> None:
        bot = _DummyBot()
        with patch("data_agent.stoplist_digest_scheduler.get_db_session", side_effect=self.SessionLocal):
            result = asyncio.run(
                stoplist_digest_scheduler.send_due_stoplist_weekly_digests(
                    bot,
                    now=datetime(2026, 4, 27, 11, 5, 0),
                    lookback_days=7,
                )
            )
            second_result = asyncio.run(
                stoplist_digest_scheduler.send_due_stoplist_weekly_digests(
                    bot,
                    now=datetime(2026, 4, 27, 11, 5, 0),
                    lookback_days=7,
                )
            )

        db = self.SessionLocal()
        try:
            deliveries = db.query(StopListWeeklyDigestDelivery).order_by(StopListWeeklyDigestDelivery.user_id.asc()).all()
        finally:
            db.close()

        self.assertEqual(result["sent"], 2)
        self.assertEqual(second_result["sent"], 0)
        self.assertEqual(len(bot.messages), 2)
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(deliveries[0].week_start_date.isoformat(), "2026-04-27")

    def test_preview_falls_back_to_direct_bot_chat_when_profile_chat_missing(self) -> None:
        with patch("data_agent.stoplist_digest_scheduler.get_db_session", side_effect=self.SessionLocal):
            payload = stoplist_digest_scheduler.build_stoplist_weekly_digest_preview(
                telegram_user_id=5550002,
                now=datetime(2026, 4, 27, 11, 5, 0),
                lookback_days=7,
            )

        self.assertTrue(payload["found"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["delivery_chat_id"], 5550002)
        self.assertEqual(payload["delivery_target"], "direct_bot_chat")
        self.assertEqual(payload["incidents_count"], 1)
        self.assertIn("Реж, Ленина 17", payload["text"])


if __name__ == "__main__":
    unittest.main()
