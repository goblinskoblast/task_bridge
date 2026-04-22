import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from bot.data_agent_handlers import _deliver_report_to_selected_chat
from data_agent.point_delivery import get_point_report_chat, match_saved_point_to_chat_title
from db.models import Base, Chat, DataAgentProfile, SavedPoint, User


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=501)


class _DummyMessage:
    def __init__(self, user_id: int, bot: _DummyBot) -> None:
        self.from_user = SimpleNamespace(id=user_id, username="priority", first_name="Priority")
        self.bot = bot


class PointDeliveryRoutingTest(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_match_saved_point_to_chat_title_matches_city_title(self):
        points = [
            SimpleNamespace(
                display_name="Асбест, ТЦ Небо, Ленинградская 26/2",
                city="Асбест",
                address="ТЦ Небо, Ленинградская 26/2",
                external_point_key=None,
            ),
            SimpleNamespace(
                display_name="Верхний Уфалей, Ленина 147",
                city="Верхний Уфалей",
                address="Ленина 147",
                external_point_key=None,
            ),
        ]

        matched = match_saved_point_to_chat_title(points, "ТурбоБот Уфалей")

        self.assertIsNotNone(matched)
        self.assertEqual(matched.display_name, "Верхний Уфалей, Ленина 147")

    async def test_deliver_report_prefers_point_specific_chat_over_profile_chat(self):
        session = self.SessionLocal()
        try:
            user = User(telegram_id=137236883, username="priority", first_name="Priority")
            session.add(user)
            session.flush()

            session.add(
                DataAgentProfile(
                    user_id=user.id,
                    stoplist_report_chat_id=-100999001,
                    stoplist_report_chat_title="Общий чат",
                )
            )
            session.add(Chat(chat_id=-100999001, chat_type="supergroup", title="Общий чат", is_active=True))
            session.add(Chat(chat_id=-100777001, chat_type="supergroup", title="ТурбоБот Асбест", is_active=True))
            session.add(
                SavedPoint(
                    user_id=user.id,
                    provider="italian_pizza",
                    city="Асбест",
                    address="ТЦ Небо, Ленинградская 26/2",
                    display_name="Асбест, ТЦ Небо, Ленинградская 26/2",
                    external_point_key=None,
                    is_active=True,
                    report_delivery_enabled=True,
                    stoplist_report_chat_id=-100777001,
                    stoplist_report_chat_title="ТурбоБот Асбест",
                    stats_interval_minutes=240,
                )
            )
            session.commit()
        finally:
            session.close()

        bot = _DummyBot()
        message = _DummyMessage(user_id=137236883, bot=bot)

        with patch("bot.data_agent_handlers.get_db_session", side_effect=self.SessionLocal):
            chat_title = await _deliver_report_to_selected_chat(
                message,
                "пришли стоп-лист по Асбест, ТЦ Небо, Ленинградская 26/2",
                "Стоп-лист пуст",
                report_category="stoplist",
                telegram_user_id=137236883,
                requester_name="@owner",
            )

        self.assertEqual(chat_title, "ТурбоБот Асбест")
        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(bot.messages[0]["chat_id"], -100777001)
        self.assertIn("Стоп-лист пуст", bot.messages[0]["text"])

        session = self.SessionLocal()
        try:
            point = session.query(SavedPoint).first()
        finally:
            session.close()

        chat_id, chat_title = get_point_report_chat(point, "stoplist")
        self.assertEqual(chat_id, -100777001)
        self.assertEqual(chat_title, "ТурбоБот Асбест")


if __name__ == "__main__":
    unittest.main()
