import os
import unittest
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from webapp_auth import (
    build_signed_webapp_url,
    build_webapp_auth_token,
    verify_webapp_auth_token,
)


class WebappAuthHelpersTest(unittest.TestCase):
    def test_build_and_verify_webapp_token_round_trip(self):
        token = build_webapp_auth_token("secret", 42, created_ts=1000, nonce="fixed")

        user_id = verify_webapp_auth_token("secret", token, ttl_seconds=3600, now_ts=2000)

        self.assertEqual(user_id, 42)

    def test_expired_webapp_token_is_rejected(self):
        token = build_webapp_auth_token("secret", 7, created_ts=1000, nonce="fixed")

        with self.assertRaisesRegex(ValueError, "expired"):
            verify_webapp_auth_token("secret", token, ttl_seconds=60, now_ts=1200)

    def test_signed_webapp_url_contains_auth_and_context_params(self):
        url = build_signed_webapp_url(
            "https://example.com",
            user_id=11,
            mode="executor",
            task_id=99,
            tab="emails",
            auth_secret="secret",
        )

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/webapp/index.html")
        self.assertEqual(params["user_id"], ["11"])
        self.assertEqual(params["mode"], ["executor"])
        self.assertEqual(params["task_id"], ["99"])
        self.assertEqual(params["tab"], ["emails"])
        self.assertIn("tb_auth", params)


if __name__ == "__main__":
    unittest.main()
