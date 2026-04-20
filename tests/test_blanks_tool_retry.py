import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from data_agent.blanks_tool import BlanksTool


class BlanksToolRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_login_submit_transient_failure_once(self):
        tool = BlanksTool()
        first_result = {
            "status": "failed",
            "message": "login form stayed open",
            "diagnostics": {"stage": "login_submit"},
        }
        recovered_result = {
            "status": "ok",
            "report_text": "красных зон нет",
            "has_red_flags": False,
            "diagnostics": {"stage": "report_read"},
        }

        with patch(
            "data_agent.blanks_tool.italian_pizza_portal_adapter.collect_blanks",
            AsyncMock(side_effect=[first_result, recovered_result]),
        ) as mocked_collect:
            result = await tool.inspect_point(
                url="https://example.com",
                username="user",
                encrypted_password="secret",
                point_name="Сухой Лог, Белинского 40",
                period_hint="за последние 3 часа",
            )

        self.assertEqual(mocked_collect.await_count, 2)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["diagnostics"]["transient_retry_recovered"])

    async def test_retries_period_selection_needs_period_once(self):
        tool = BlanksTool()
        first_result = {
            "status": "needs_period",
            "message": "period chip was stale",
            "diagnostics": {"stage": "period_selection"},
        }
        second_result = {
            "status": "needs_period",
            "message": "period chip still unavailable",
            "diagnostics": {"stage": "period_selection"},
        }

        with patch(
            "data_agent.blanks_tool.italian_pizza_portal_adapter.collect_blanks",
            AsyncMock(side_effect=[first_result, second_result]),
        ) as mocked_collect:
            result = await tool.inspect_point(
                url="https://example.com",
                username="user",
                encrypted_password="secret",
                point_name="Сухой Лог, Белинского 40",
                period_hint="за последние 3 часа",
            )

        self.assertEqual(mocked_collect.await_count, 2)
        self.assertEqual(result["status"], "needs_period")
        self.assertTrue(result["diagnostics"]["transient_retry_attempted"])

    async def test_does_not_retry_ok_result(self):
        tool = BlanksTool()
        ok_result = {
            "status": "ok",
            "report_text": "красных зон нет",
            "diagnostics": {"stage": "report_read"},
        }

        with patch(
            "data_agent.blanks_tool.italian_pizza_portal_adapter.collect_blanks",
            AsyncMock(return_value=ok_result),
        ) as mocked_collect:
            result = await tool.inspect_point(
                url="https://example.com",
                username="user",
                encrypted_password="secret",
                point_name="Сухой Лог, Белинского 40",
                period_hint="за последние 3 часа",
            )

        self.assertEqual(mocked_collect.await_count, 1)
        self.assertEqual(result, ok_result)

    async def test_does_not_retry_non_transient_failure_stage(self):
        tool = BlanksTool()
        failed_result = {
            "status": "failed",
            "message": "point was not found",
            "diagnostics": {"stage": "point_selection"},
        }

        with patch(
            "data_agent.blanks_tool.italian_pizza_portal_adapter.collect_blanks",
            AsyncMock(return_value=failed_result),
        ) as mocked_collect:
            result = await tool.inspect_point(
                url="https://example.com",
                username="user",
                encrypted_password="secret",
                point_name="Сухой Лог, Белинского 40",
                period_hint="за последние 3 часа",
            )

        self.assertEqual(mocked_collect.await_count, 1)
        self.assertEqual(result, failed_result)
