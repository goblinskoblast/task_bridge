import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.data_agent_client import DataAgentClient, DataAgentResponseError, GENERIC_AGENT_RETRY_MESSAGE


class DataAgentClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_uses_extended_timeout_and_retry(self):
        client = DataAgentClient(
            base_url="https://example.com",
            timeout_seconds=30,
            chat_timeout_seconds=90,
        )
        client._request = AsyncMock(return_value={"status": "ok"})

        payload = {"user_id": 1, "message": "ping"}
        result = await client.chat(payload)

        self.assertEqual(result["status"], "ok")
        client._request.assert_awaited_once_with(
            "POST",
            "/chat",
            json=payload,
            timeout_seconds=90,
            retry_attempts=2,
        )

    def test_decode_payload_raises_response_error_for_html(self):
        with self.assertRaises(DataAgentResponseError) as ctx:
            DataAgentClient._decode_payload("<html>bad gateway</html>", 502, "https://example.com/chat")

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.user_message, GENERIC_AGENT_RETRY_MESSAGE)
        self.assertNotIn("некорректный", ctx.exception.user_message.lower())

    def test_build_http_error_hides_internal_status_details(self):
        error = DataAgentClient._build_http_error(
            503,
            {"detail": "Service unavailable"},
            '{"detail":"Service unavailable"}',
            "https://example.com/chat",
        )

        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.user_message, GENERIC_AGENT_RETRY_MESSAGE)
        self.assertNotIn("сервис", error.user_message.lower())

    def test_build_http_error_hides_internal_auth_failure(self):
        error = DataAgentClient._build_http_error(
            403,
            {"detail": "forbidden"},
            '{"detail":"forbidden"}',
            "https://example.com/chat",
        )

        self.assertEqual(error.status_code, 403)
        self.assertEqual(error.user_message, GENERIC_AGENT_RETRY_MESSAGE)
        self.assertNotIn("внутрен", error.user_message.lower())
        self.assertNotIn("railway", error.user_message.lower())


if __name__ == "__main__":
    unittest.main()
