import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from bot.data_agent_handlers import _build_user_safe_agent_answer, _dispatch_agent_request
from data_agent import scenario_engine
from data_agent.agent_runtime import AgentSessionSnapshot, DataAgentRuntime
from data_agent.point_statistics import point_statistics_service
from data_agent.service import DataAgentService
from db.models import Base, DataAgentMonitorConfig, DataAgentSystem, SavedPoint, User


PRIORITY_TELEGRAM_ID = 137236883
PRIORITY_POINT = "Сухой Лог, Белинского 40"


class _DummyMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=PRIORITY_TELEGRAM_ID, username="priority", first_name="Priority")

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class PriorityUserGoldenFlowsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = DataAgentRuntime()
        self.service = DataAgentService()
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._seed_priority_user(
            [
                PRIORITY_POINT,
                "Реж, Ленина 17",
            ]
        )

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_priority_user(self, point_names: list[str]) -> None:
        db = self.SessionLocal()
        try:
            user = User(
                telegram_id=PRIORITY_TELEGRAM_ID,
                username="priority",
                first_name="Priority",
                last_name=None,
                is_bot=False,
            )
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
            for point_name in point_names:
                city, _, address = point_name.partition(",")
                db.add(
                    SavedPoint(
                        user_id=user.id,
                        system_id=system.id,
                        provider="italian_pizza",
                        city=city.strip(),
                        address=address.strip(),
                        display_name=point_name,
                        is_active=True,
                    )
                )
            db.commit()
        finally:
            db.close()

    def test_priority_stoplist_flow_keeps_current_category_and_age_contract(self) -> None:
        text = point_statistics_service._render_stoplist_report(
            PRIORITY_POINT,
            ["Маргарита", "Пепперони", "Четыре сыра"],
            {
                "added": ["Четыре сыра"],
                "removed": ["Карбонара"],
                "stayed": ["Маргарита", "Пепперони"],
            },
            has_history=True,
            is_saved_point=True,
            current_age_hours={"Маргарита": 13, "Пепперони": 2, "Четыре сыра": 1},
            removed_age_hours={"Карбонара": 3},
        )

        self.assertIn("Новые в стопе", text)
        self.assertIn("Уже в стопе", text)
        self.assertIn("Ушли из стопа", text)
        self.assertIn("1. 🟡 Четыре сыра", text)
        self.assertIn("1. 🔴 Маргарита", text)
        self.assertIn("2. 🟡 Пепперони", text)
        self.assertIn("1. Карбонара", text)
        self.assertIn("в стопе 1 день", text)
        self.assertIn("в стопе 2 часа", text)
        self.assertIn("была в стопе 3 часа", text)

    def test_priority_stoplist_request_stays_in_stoplist_scenario(self) -> None:
        decision = self.runtime._rule_based_decision(
            "пришли стоп-лист по Сухой Лог Белинского 40",
            AgentSessionSnapshot(user_id=PRIORITY_TELEGRAM_ID),
            1,
        )

        self.assertEqual(decision.scenario, "stoplist_report")
        self.assertEqual(decision.selected_tools, ["stoplist_tool"])
        self.assertEqual(decision.slots.get("point_name"), PRIORITY_POINT)
        self.assertEqual(decision.missing_slots, [])

    def test_priority_show_enabled_phrase_maps_to_monitor_list(self) -> None:
        decision = self.runtime._rule_based_decision(
            "что у меня включено",
            AgentSessionSnapshot(user_id=PRIORITY_TELEGRAM_ID),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.slots.get("monitor_action"), "list")
        self.assertEqual(decision.missing_slots, [])

    def test_priority_blanks_all_points_default_to_three_hours_and_hide_internal_noise(self) -> None:
        decision = self.runtime._rule_based_decision(
            "покажи бланки по всем добавленным точкам",
            AgentSessionSnapshot(user_id=PRIORITY_TELEGRAM_ID),
            1,
        )

        async def inspect_point(**kwargs):
            point_name = kwargs["point_name"]
            if point_name == "Реж, Ленина 17":
                return {
                    "status": "ok",
                    "report_text": "Реж: есть красный бланк по мясу.",
                    "has_red_flags": True,
                }
            return {
                "status": "failed",
                "message": "Trace: abc\nЭтап: login_submit\nPage.evaluate failed\n????",
                "report_text": "Причина: period_selection",
            }

        with patch.object(scenario_engine, "get_db_session", side_effect=self.SessionLocal):
            with patch.object(scenario_engine.blanks_tool, "inspect_point", side_effect=inspect_point):
                result = asyncio.run(
                    scenario_engine._run_saved_points_blanks_report(
                        user_id=PRIORITY_TELEGRAM_ID,
                        period_hint=decision.slots["period_hint"],
                    )
                )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertTrue(decision.slots.get("all_points"))
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["has_red_flags"])
        self.assertEqual(result["red_points"], ["Реж, Ленина 17"])
        self.assertEqual(result["failed_points"], [PRIORITY_POINT])
        self.assertIn("Период: за последние 3 часа", result["report_text"])
        self.assertIn("С красными бланками: Реж, Ленина 17", result["report_text"])
        self.assertIn("Не удалось проверить: Сухой Лог, Белинского 40", result["report_text"])
        self.assertNotIn("Trace:", result["report_text"])
        self.assertNotIn("Этап:", result["report_text"])
        self.assertNotIn("Причина:", result["report_text"])
        self.assertNotIn("Page.evaluate", result["report_text"])
        self.assertNotIn("????", result["report_text"])

    def test_priority_monitor_enable_defaults_interval_and_business_window(self) -> None:
        decision = self.runtime._rule_based_decision(
            "мониторь бланки по Сухой Лог Белинского 40",
            AgentSessionSnapshot(user_id=PRIORITY_TELEGRAM_ID),
            1,
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            note = self.service._upsert_monitor(
                user_id=PRIORITY_TELEGRAM_ID,
                scenario=decision.scenario,
                point_name=decision.slots["point_name"],
                interval_minutes=decision.slots.get("monitor_interval_minutes"),
                interval_source=decision.slots.get("monitor_interval_source"),
                start_hour=decision.slots.get("monitor_start_hour"),
                end_hour=decision.slots.get("monitor_end_hour"),
            )

        session = self.SessionLocal()
        try:
            config = (
                session.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.point_name == PRIORITY_POINT,
                    DataAgentMonitorConfig.monitor_type == "blanks",
                )
                .first()
            )
        finally:
            session.close()

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("monitor_action"), "enable")
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)
        self.assertEqual(decision.slots.get("monitor_interval_source"), "default_intent")
        self.assertIsNotNone(config)
        self.assertEqual(config.check_interval_minutes, 180)
        self.assertEqual(config.active_from_hour, 8)
        self.assertEqual(config.active_to_hour, 20)
        self.assertIn("каждые 3 часа", note or "")
        self.assertIn("с 10:00 до 22:00 по Екатеринбургу", note or "")

    def test_priority_failed_blanks_answer_stays_user_safe(self) -> None:
        answer = _build_user_safe_agent_answer(
            {
                "status": "failed",
                "scenario": "blanks_report",
                "answer": "Trace: abc\nЭтап: login_submit\nPage.evaluate failed\nПричина: login_submit\n????",
            }
        )

        self.assertEqual(answer, "Не удалось получить отчет по бланкам. Попробуйте позже.")


class PriorityUserGoldenDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_priority_long_blanks_request_gets_fast_ack(self) -> None:
        message = _DummyMessage()

        with patch("bot.data_agent_handlers._schedule_background_agent_request") as mocked_schedule:
            await _dispatch_agent_request(message, "покажи бланки по всем добавленным точкам")

        self.assertEqual(
            message.answers,
            ["⏳ Принял запрос. Собираю отчёт по всем точкам, это может занять пару минут."],
        )
        mocked_schedule.assert_called_once_with(
            message,
            "покажи бланки по всем добавленным точкам",
            send_progress=False,
        )


if __name__ == "__main__":
    unittest.main()
