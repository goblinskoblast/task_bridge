import os
import unittest
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from webapp_auth import (
    build_signed_webapp_url,
    build_webapp_auth_token,
    resolve_authenticated_webapp_user,
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

    def test_signed_token_fallback_works_when_telegram_init_is_invalid(self):
        auth_source, auth_payload = resolve_authenticated_webapp_user(
            init_data="broken-init",
            signed_token="signed-token",
            verify_telegram_init_data=lambda _: (_ for _ in ()).throw(ValueError("Telegram init data has expired")),
            verify_signed_token=lambda token: 77 if token == "signed-token" else None,
        )

        self.assertEqual(auth_source, "signed")
        self.assertEqual(auth_payload, 77)

    def test_init_error_is_raised_when_no_signed_fallback_exists(self):
        with self.assertRaisesRegex(ValueError, "Telegram init data has expired"):
            resolve_authenticated_webapp_user(
                init_data="broken-init",
                signed_token=None,
                verify_telegram_init_data=lambda _: (_ for _ in ()).throw(ValueError("Telegram init data has expired")),
                verify_signed_token=lambda _: 0,
            )


if __name__ == "__main__":
    unittest.main()
