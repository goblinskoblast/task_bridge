import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from data_agent.main import verify_internal_api_access


class DataAgentMainAuthTest(unittest.TestCase):
    def test_verify_internal_api_access_is_async(self) -> None:
        self.assertTrue(inspect.iscoroutinefunction(verify_internal_api_access))

    def test_verify_internal_api_access_allows_missing_token_config(self) -> None:
        request = SimpleNamespace(headers={})
        with patch("data_agent.main.INTERNAL_API_TOKEN", ""):
            asyncio.run(verify_internal_api_access(request))

    def test_verify_internal_api_access_rejects_invalid_token(self) -> None:
        request = SimpleNamespace(headers={"X-Internal-Token": "wrong"})
        with patch("data_agent.main.INTERNAL_API_TOKEN", "expected-token"):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(verify_internal_api_access(request))

        self.assertEqual(context.exception.status_code, 403)

    def test_verify_internal_api_access_accepts_valid_token(self) -> None:
        request = SimpleNamespace(headers={"X-Internal-Token": "expected-token"})
        with patch("data_agent.main.INTERNAL_API_TOKEN", "expected-token"):
            asyncio.run(verify_internal_api_access(request))


if __name__ == "__main__":
    unittest.main()
