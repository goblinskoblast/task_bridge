import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from db.models import Base, DataAgentMonitorConfig, DataAgentMonitorEvent, StopListIncident, User
from data_agent import monitor_scheduler


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self._next_message_id = 3100

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id, date=datetime(2026, 4, 23, 12, 0, 0))


class StopListMonitorCardsTest(unittest.TestCase):
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
            user = User(
                telegram_id=555001,
                username="tester",
                first_name="Test",
                last_name=None,
                is_bot=False,
            )
            db.add(user)
            db.flush()

            stoplist_config = DataAgentMonitorConfig(
                user_id=user.id,
                system_name="italian_pizza",
                monitor_type="stoplist",
                point_name="Сухой Лог, Белинского 40",
                check_interval_minutes=180,
                is_active=True,
            )
            db.add(stoplist_config)
            db.commit()
            db.refresh(stoplist_config)
            self.stoplist_config_id = stoplist_config.id
            self.detached_stoplist_config = stoplist_config
        finally:
            db.close()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_run_stoplist_monitor_uses_new_case_card_for_first_incident(self):
        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист:\n- Маргарита",
            "items": ["Маргарита"],
            "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
            "alert_hash": "stoplist-open",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.stoplist_tool,
                "collect_for_point",
                new=AsyncMock(return_value=result),
            ):
                with patch.object(
                    monitor_scheduler.point_statistics_service,
                    "enrich_stoplist_report",
                    return_value=result,
                ):
                    asyncio.run(monitor_scheduler._run_stoplist_monitor(bot, self.detached_stoplist_config))

        db = self.SessionLocal()
        try:
            event = (
                db.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.stoplist_config_id)
                .first()
            )
            incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.monitor_config_id == self.stoplist_config_id)
                .first()
            )
        finally:
            db.close()

        self.assertIsNotNone(event)
        self.assertIsNotNone(incident)
        self.assertEqual(event.title, "Новый стоп-лист: Сухой Лог, Белинского 40")
        self.assertIn("Новый стоп-лист", event.body or "")
        self.assertIn("Реакция: без реакции", event.body or "")
        self.assertIn("Чтобы отметить статус", event.body or "")
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("Новый стоп-лист", bot.messages[0].get("text", ""))
        self.assertIn("<b>Кейс:</b> новый", bot.messages[0].get("text", ""))
        self.assertIn("<b>Реакция:</b> без реакции", bot.messages[0].get("text", ""))

    def test_run_stoplist_monitor_uses_ongoing_case_card_with_manager_reaction(self):
        bot = _DummyBot()
        result = {
            "status": "ok",
            "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист:\n- Маргарита",
            "items": ["Маргарита"],
            "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
            "alert_hash": "stoplist-open",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.stoplist_tool,
                "collect_for_point",
                new=AsyncMock(side_effect=[result, result]),
            ):
                with patch.object(
                    monitor_scheduler.point_statistics_service,
                    "enrich_stoplist_report",
                    side_effect=[result, result],
                ):
                    asyncio.run(monitor_scheduler._run_stoplist_monitor(bot, self.detached_stoplist_config))

                    db = self.SessionLocal()
                    try:
                        incident = (
                            db.query(StopListIncident)
                            .filter(StopListIncident.monitor_config_id == self.stoplist_config_id)
                            .first()
                        )
                        incident.manager_status = "accepted"
                        db.commit()
                    finally:
                        db.close()

                    asyncio.run(monitor_scheduler._run_stoplist_monitor(bot, self.detached_stoplist_config))

        db = self.SessionLocal()
        try:
            events = (
                db.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.stoplist_config_id)
                .order_by(DataAgentMonitorEvent.id.asc())
                .all()
            )
        finally:
            db.close()

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].title, "Стоп-лист продолжается: Сухой Лог, Белинского 40")
        self.assertEqual(len(bot.messages), 2)
        self.assertIn("Стоп-лист продолжается", bot.messages[1].get("text", ""))
        self.assertIn("<b>Реакция:</b> принято", bot.messages[1].get("text", ""))
        self.assertNotIn("Чтобы отметить статус", bot.messages[1].get("text", ""))

    def test_run_stoplist_monitor_uses_resolved_case_card_when_items_clear(self):
        bot = _DummyBot()
        open_result = {
            "status": "ok",
            "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист:\n- Маргарита",
            "items": ["Маргарита"],
            "delta": {"added": ["Маргарита"], "removed": [], "stayed": []},
            "alert_hash": "stoplist-open",
        }
        resolved_result = {
            "status": "ok",
            "report_text": "Точка: Сухой Лог, Белинского 40\nСтоп-лист: недоступных позиций не найдено.",
            "items": [],
            "delta": {"added": [], "removed": ["Маргарита"], "stayed": []},
            "alert_hash": "stoplist-clear",
        }

        with patch.object(monitor_scheduler, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(
                monitor_scheduler.stoplist_tool,
                "collect_for_point",
                new=AsyncMock(side_effect=[open_result, resolved_result]),
            ):
                with patch.object(
                    monitor_scheduler.point_statistics_service,
                    "enrich_stoplist_report",
                    side_effect=[open_result, resolved_result],
                ):
                    asyncio.run(monitor_scheduler._run_stoplist_monitor(bot, self.detached_stoplist_config))
                    asyncio.run(monitor_scheduler._run_stoplist_monitor(bot, self.detached_stoplist_config))

        db = self.SessionLocal()
        try:
            incident = (
                db.query(StopListIncident)
                .filter(StopListIncident.monitor_config_id == self.stoplist_config_id)
                .first()
            )
            events = (
                db.query(DataAgentMonitorEvent)
                .filter(DataAgentMonitorEvent.config_id == self.stoplist_config_id)
                .order_by(DataAgentMonitorEvent.id.asc())
                .all()
            )
        finally:
            db.close()

        self.assertIsNotNone(incident)
        self.assertEqual(incident.status, "resolved")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].title, "Стоп-лист нормализовался: Сухой Лог, Белинского 40")
        self.assertEqual(len(bot.messages), 2)
        self.assertIn("Стоп-лист нормализовался", bot.messages[1].get("text", ""))
        self.assertIn("<b>Кейс:</b> нормализовался", bot.messages[1].get("text", ""))
        self.assertNotIn("Чтобы отметить статус", bot.messages[1].get("text", ""))


if __name__ == "__main__":
    unittest.main()
