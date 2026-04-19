import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent import scenario_engine
from db.models import Base, DataAgentSystem, SavedPoint, User


class SavedPointsBlanksReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.telegram_id = 137236883

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_user_with_points(self, point_names: list[str]) -> None:
        db = self.SessionLocal()
        try:
            user = User(telegram_id=self.telegram_id, username="priority")
            db.add(user)
            db.flush()
            system = DataAgentSystem(
                user_id=user.id,
                system_name="italian_pizza",
                url="https://italianpizza.example",
                login="priority-login",
                encrypted_password="encrypted",
                is_active=True,
            )
            db.add(system)
            db.flush()
            for index, point_name in enumerate(point_names, start=1):
                city, _, address = point_name.partition(",")
                db.add(
                    SavedPoint(
                        user_id=user.id,
                        system_id=system.id,
                        provider="italian_pizza",
                        city=city.strip() or f"Город {index}",
                        address=address.strip() or f"Адрес {index}",
                        display_name=point_name,
                        is_active=True,
                    )
                )
            db.commit()
        finally:
            db.close()

    def test_red_blanks_without_report_text_still_get_user_visible_signal(self):
        text = scenario_engine._blanks_result_text_or_fallback(
            {"status": "ok", "has_red_flags": True},
            failure_text="Не удалось проверить эту точку.",
        )

        self.assertIn("Есть красные бланки", text)
        self.assertNotIn("Отчёт собран", text)

    def test_all_points_blanks_keeps_red_result_when_one_point_fails(self):
        self._seed_user_with_points(
            [
                "Асбест, Ленина 1",
                "Реж, Ленина 17",
                "Сухой Лог, Белинского 40",
            ]
        )

        async def inspect_point(**kwargs):
            point_name = kwargs["point_name"]
            if point_name == "Асбест, Ленина 1":
                return {
                    "status": "ok",
                    "report_text": "Асбест: красных бланков не видно.",
                    "has_red_flags": False,
                }
            if point_name == "Реж, Ленина 17":
                return {
                    "status": "ok",
                    "report_text": "Реж: есть красный бланк по мясу.",
                    "has_red_flags": True,
                }
            return {
                "status": "failed",
                "message": "Trace: abc\nЭтап: period_selection\nPage.evaluate failed\n????",
                "report_text": "Причина: внутренний сбой login_submit",
            }

        with patch.object(scenario_engine, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(scenario_engine.blanks_tool, "inspect_point", AsyncMock(side_effect=inspect_point)):
                result = asyncio.run(
                    scenario_engine._run_saved_points_blanks_report(
                        user_id=self.telegram_id,
                        period_hint="за последние 3 часа",
                    )
                )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["has_red_flags"])
        self.assertEqual(result["checked_points"], 2)
        self.assertEqual(result["total_points"], 3)
        self.assertEqual(result["red_points"], ["Реж, Ленина 17"])
        self.assertEqual(result["failed_points"], ["Сухой Лог, Белинского 40"])
        self.assertIn("Бланки по сохранённым точкам", result["report_text"])
        self.assertIn("Период: за последние 3 часа", result["report_text"])
        self.assertIn("Проверено: 2 из 3", result["report_text"])
        self.assertIn("Красные зоны: 1", result["report_text"])
        self.assertIn("С красными бланками: Реж, Ленина 17", result["report_text"])
        self.assertIn("Не удалось проверить: Сухой Лог, Белинского 40", result["report_text"])
        self.assertIn("Реж: есть красный бланк по мясу.", result["report_text"])
        self.assertIn("Не удалось проверить эту точку. Попробуйте позже.", result["report_text"])
        self.assertNotIn("Trace:", result["report_text"])
        self.assertNotIn("Этап:", result["report_text"])
        self.assertNotIn("Причина:", result["report_text"])
        self.assertNotIn("Page.evaluate", result["report_text"])
        self.assertNotIn("????", result["report_text"])

    def test_all_points_blanks_all_failures_are_user_safe(self):
        self._seed_user_with_points(["Сухой Лог, Белинского 40"])

        failed_result = {
            "status": "needs_period",
            "message": "Trace: internal\nЭтап: login_submit\nPage.evaluate failed",
            "report_text": "Причина: period_selection",
        }

        with patch.object(scenario_engine, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(scenario_engine.blanks_tool, "inspect_point", AsyncMock(return_value=failed_result)):
                result = asyncio.run(
                    scenario_engine._run_saved_points_blanks_report(
                        user_id=self.telegram_id,
                        period_hint="за последние 3 часа",
                    )
                )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["has_red_flags"])
        self.assertEqual(result["checked_points"], 0)
        self.assertEqual(result["failed_points"], ["Сухой Лог, Белинского 40"])
        self.assertIn("Проверено: 0 из 1", result["report_text"])
        self.assertIn("Красные зоны: нет", result["report_text"])
        self.assertIn("Не удалось проверить эту точку. Попробуйте позже.", result["report_text"])
        self.assertNotIn("Trace:", result["report_text"])
        self.assertNotIn("Этап:", result["report_text"])
        self.assertNotIn("Причина:", result["report_text"])
        self.assertNotIn("Page.evaluate", result["report_text"])


if __name__ == "__main__":
    unittest.main()
