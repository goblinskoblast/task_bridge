import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.review_report import ReviewReportService
from data_agent.scenario_engine import ReviewsReportScenario


class ReviewReportPointFilteringTest(unittest.IsolatedAsyncioTestCase):
    async def test_filter_rows_by_point_matches_aliases(self):
        service = ReviewReportService()
        rows = [
            {"branch": "Верхний Уфалей", "review": "Все хорошо", "date": "2026-04-07 12:00:00"},
            {"branch": "Екатеринбург, ул. Сулимова, 31А", "review": "Долго ждали", "date": "2026-04-07 13:00:00"},
        ]

        filtered, matched_branches = service._filter_rows_by_point(rows, "Верхний Уфалей, Ленина 147")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(matched_branches, ["Верхний Уфалей"])

    async def test_build_summary_keeps_zero_rows_as_ok_for_point(self):
        service = ReviewReportService()

        summary = service._build_summary(
            [],
            service._resolve_window("отзывы за сегодня"),
            "https://example.com/reviews.csv",
            point_name="Верхний Уфалей, Ленина 147",
            matched_branches=[],
        )

        self.assertEqual(summary["status"], "ok")
        self.assertIn("По выбранной точке", summary["report_text"])

    async def test_reviews_scenario_prefers_sheet_for_point_queries(self):
        scenario = ReviewsReportScenario()
        sheet_result = {"status": "ok", "report_text": "sheet report"}

        with patch(
            "data_agent.scenario_engine.review_report_service.build_report",
            AsyncMock(return_value=sheet_result),
        ) as mocked_build_report, patch(
            "data_agent.scenario_engine._run_public_reviews_browser",
            AsyncMock(),
        ) as mocked_browser:
            execution = await scenario.execute(
                user_id=17,
                user_message="собери отзывы по Верхний Уфалей, Ленина 147 за неделю",
                slots={"point_name": "Верхний Уфалей, Ленина 147"},
                systems=[],
            )

        self.assertEqual(execution.tool_results["review_tool"], sheet_result)
        mocked_build_report.assert_awaited_once_with(
            "собери отзывы по Верхний Уфалей, Ленина 147 за неделю",
            point_name="Верхний Уфалей, Ленина 147",
        )
        mocked_browser.assert_not_awaited()

    async def test_reviews_scenario_uses_browser_for_maps_queries(self):
        scenario = ReviewsReportScenario()
        browser_result = {"status": "ok", "report_text": "maps report"}

        with patch(
            "data_agent.scenario_engine.review_report_service.build_report",
            AsyncMock(return_value={"status": "ok", "report_text": "sheet report"}),
        ) as mocked_build_report, patch(
            "data_agent.scenario_engine._run_public_reviews_browser",
            AsyncMock(return_value=browser_result),
        ) as mocked_browser:
            execution = await scenario.execute(
                user_id=17,
                user_message="собери отзывы по Верхний Уфалей, Ленина 147 на 2гис",
                slots={"point_name": "Верхний Уфалей, Ленина 147"},
                systems=[],
            )

        self.assertEqual(execution.tool_results["review_tool"], browser_result)
        mocked_build_report.assert_not_awaited()
        mocked_browser.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
