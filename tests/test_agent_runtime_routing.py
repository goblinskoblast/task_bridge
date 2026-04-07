import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent.agent_runtime import AgentDecision, AgentSessionSnapshot, DataAgentRuntime


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
        self.assertEqual(decision.slots.get("period_hint"), "предыдущие 3 часа")

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


if __name__ == "__main__":
    unittest.main()
