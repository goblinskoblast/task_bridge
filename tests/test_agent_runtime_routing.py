import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent.agent_runtime import AgentDecision, AgentSessionSnapshot, DataAgentRuntime
from data_agent.italian_pizza import resolve_italian_pizza_point


class AgentRuntimeRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = DataAgentRuntime()

    def test_rule_based_decision_recognizes_simple_blanks_keyword(self):
        decision = self.runtime._rule_based_decision(
            "проверь бланки для Екатеринбург Сулимова 31А за 3 часа",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), "Екатеринбург, ул. Сулимова, 31А")
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")

    def test_merge_decisions_does_not_carry_point_into_unrelated_scenario(self):
        session = AgentSessionSnapshot(
            user_id=1,
            scenario="stoplist_report",
            slots={"point_name": "Верхний Уфалей, Ленина 147", "period_hint": "предыдущие 12 часов"},
        )
        base = AgentDecision(
            scenario="reviews_report",
            selected_tools=["review_tool"],
            slots={"source_message": "отзывы за сегодня"},
            missing_slots=[],
            reasoning="test",
        )

        merged = self.runtime._merge_decisions(base, None, session)

        self.assertEqual(merged.scenario, "reviews_report")
        self.assertNotIn("point_name", merged.slots)
        self.assertNotIn("period_hint", merged.slots)

    def test_merge_decisions_keeps_point_for_followup(self):
        session = AgentSessionSnapshot(
            user_id=1,
            scenario="stoplist_report",
            slots={"point_name": "Верхний Уфалей, Ленина 147"},
        )
        base = AgentDecision(
            scenario="stoplist_report",
            selected_tools=["stoplist_tool"],
            slots={"source_message": "по этой точке еще раз"},
            missing_slots=[],
            reasoning="test",
        )

        merged = self.runtime._merge_decisions(base, None, session)

        self.assertEqual(merged.slots.get("point_name"), "Верхний Уфалей, Ленина 147")

    def test_rule_based_decision_detects_all_saved_points_request_for_blanks(self):
        decision = self.runtime._rule_based_decision(
            "Покажи мне бланки загрузки по всем добавленным точкам.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertTrue(decision.slots.get("all_points"))
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_extracts_monitoring_from_blanks_phrase(self):
        decision = self.runtime._rule_based_decision(
            "Присылай мне бланки по сухой лог Белинского 40 каждые 3 часа.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), "Сухой Лог, Белинского 40")
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_defaults_monitor_interval_for_blanks_monitor_intent(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        expected_period = self.runtime._extract_period_hint("за последние 3 часа")
        decision = self.runtime._rule_based_decision(
            "Мониторь бланки по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)
        self.assertEqual(decision.slots.get("monitor_interval_source"), "default_intent")
        self.assertEqual(decision.slots.get("period_hint"), expected_period)

    def test_rule_based_decision_defaults_monitor_interval_for_stoplist_monitor_intent(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Следи за стоп-листом по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "stoplist_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)

    def test_rule_based_decision_extracts_daily_monitor_interval(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Присылай стоп-лист по Сухой Лог Белинского 40 каждый день.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "stoplist_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 1440)
        self.assertEqual(decision.slots.get("monitor_interval_source"), "explicit")

    def test_rule_based_decision_extracts_disable_action_for_blanks_monitor(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Не присылай мне бланки по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_action"), "disable")
        self.assertIsNone(decision.slots.get("monitor_interval_minutes"))
        self.assertIsNone(decision.slots.get("period_hint"))

    def test_rule_based_decision_extracts_disable_action_for_stoplist_monitor(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Отключи стоп-лист по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "stoplist_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_action"), "disable")
        self.assertIsNone(decision.slots.get("monitor_interval_minutes"))

    def test_rule_based_decision_lists_active_monitors_from_free_text(self):
        decision = self.runtime._rule_based_decision(
            "Покажи мои активные мониторинги.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.selected_tools, ["orchestrator"])
        self.assertEqual(decision.slots.get("monitor_action"), "list")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_understands_short_show_monitors_phrase(self):
        decision = self.runtime._rule_based_decision(
            "покажи мониторинги",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.selected_tools, ["orchestrator"])
        self.assertEqual(decision.slots.get("monitor_action"), "list")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_understands_what_is_enabled_as_monitor_list(self):
        decision = self.runtime._rule_based_decision(
            "Что у меня включено?",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.slots.get("monitor_action"), "list")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_understands_flexible_monitor_list_phrases(self):
        phrases = [
            "Какие у меня мониторинги включены?",
            "Какие отчёты сейчас присылаются?",
            "Что сейчас включено по рассылкам?",
        ]

        for phrase in phrases:
            with self.subTest(phrase=phrase):
                decision = self.runtime._rule_based_decision(
                    phrase,
                    AgentSessionSnapshot(user_id=1),
                    1,
                )

                self.assertEqual(decision.scenario, "monitor_management")
                self.assertEqual(decision.slots.get("monitor_action"), "list")
                self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_routes_generic_monitor_disable_by_point(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Останови мониторинг по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertEqual(decision.slots.get("monitor_action"), "disable")
        self.assertEqual(decision.missing_slots, [])

    def test_rule_based_decision_asks_point_for_generic_monitor_disable(self):
        decision = self.runtime._rule_based_decision(
            "Останови мониторинг.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "monitor_management")
        self.assertEqual(decision.slots.get("monitor_action"), "disable")
        self.assertEqual(decision.missing_slots, ["point_name"])

    def test_rule_based_decision_keeps_one_off_blanks_request_without_monitor_interval(self):
        expected_point_name = resolve_italian_pizza_point("Сухой Лог Белинского 40").display_name
        decision = self.runtime._rule_based_decision(
            "Пришли мне бланки по Сухой Лог Белинского 40.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), expected_point_name)
        self.assertIsNone(decision.slots.get("monitor_interval_minutes"))

    def test_rule_based_decision_extracts_monitor_window_from_spoken_phrase(self):
        decision = self.runtime._rule_based_decision(
            "Присылай мне бланки по сухой лог Белинского 40 каждые 3 часа с 10 утра по 22 вечера.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), "Сухой Лог, Белинского 40")
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)
        self.assertEqual(decision.slots.get("monitor_start_hour"), 10)
        self.assertEqual(decision.slots.get("monitor_end_hour"), 22)

    def test_rule_based_decision_extracts_update_action_for_monitor_window_only(self):
        decision = self.runtime._rule_based_decision(
            "Измени окно мониторинга бланков по Сухой Лог Белинского 40 с 11 до 21.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertEqual(decision.slots.get("point_name"), "Сухой Лог, Белинского 40")
        self.assertEqual(decision.slots.get("monitor_action"), "update")
        self.assertEqual(decision.slots.get("monitor_interval_minutes"), 180)
        self.assertEqual(decision.slots.get("monitor_interval_source"), "default_intent")
        self.assertEqual(decision.slots.get("monitor_start_hour"), 11)
        self.assertEqual(decision.slots.get("monitor_end_hour"), 21)

    def test_rule_based_decision_recognizes_stoplist_slang_and_noisy_point(self):
        decision = self.runtime._rule_based_decision(
            "Дай мне отчёт по стопам верхнего фолия Ленина 147.",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "stoplist_report")
        self.assertEqual(decision.slots.get("point_name"), "Верхний Уфалей, Ленина 147")

    def test_resolve_italian_pizza_point_supports_noisy_ufaley_alias(self):
        point = resolve_italian_pizza_point("верхнего фолия ленина 147")
        self.assertIsNotNone(point)
        self.assertEqual(point.display_name, "Верхний Уфалей, Ленина 147")


class AgentRuntimeAsyncRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_decide_skips_llm_for_explicit_stoplist_request(self):
        runtime = DataAgentRuntime()

        with patch.object(runtime, "load_session", return_value=AgentSessionSnapshot(user_id=1)):
            with patch.object(runtime, "_llm_decision", AsyncMock(return_value=None)) as mocked_llm:
                decision = await runtime.decide(
                    1,
                    "проверь стоп-лист по точке Екатеринбург, Ленина 147",
                    systems_count=1,
                )

        self.assertEqual(decision.scenario, "stoplist_report")
        mocked_llm.assert_not_awaited()


class AgentRuntimePeriodHintTest(unittest.TestCase):
    def test_rule_based_blanks_without_period_defaults_to_three_hours(self):
        runtime = DataAgentRuntime()
        decision = runtime._rule_based_decision(
            "Покажи бланки загрузки по точке Асбест, ТЦ Небо, Ленинградская 26/2",
            AgentSessionSnapshot(user_id=1),
            1,
        )
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")

    def test_rule_based_blanks_for_all_saved_points_defaults_to_three_hours(self):
        runtime = DataAgentRuntime()
        decision = runtime._rule_based_decision(
            "покажи бланки по всем добавленным точкам",
            AgentSessionSnapshot(user_id=1),
            1,
        )

        self.assertEqual(decision.scenario, "blanks_report")
        self.assertTrue(decision.slots.get("all_points"))
        self.assertEqual(decision.slots.get("period_hint"), "за последние 3 часа")

    def test_extract_period_hint_supports_six_hours(self):
        runtime = DataAgentRuntime()
        period = runtime._extract_period_hint("проверь бланки за последние 6 часов")
        self.assertEqual(period, "за последние 6 часов")

    def test_extract_period_hint_supports_last_day_for_reviews(self):
        runtime = DataAgentRuntime()
        period = runtime._extract_period_hint("собери отзывы по точке за сутки")
        self.assertEqual(period, "последние сутки")

    def test_extract_period_hint_supports_last_week_for_reviews(self):
        runtime = DataAgentRuntime()
        period = runtime._extract_period_hint("собери отзывы по точке за неделю")
        self.assertEqual(period, "за последнюю неделю")


if __name__ == "__main__":
    unittest.main()
