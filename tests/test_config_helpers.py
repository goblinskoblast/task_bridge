import unittest

from config_helpers import derive_internal_api_token, derive_webhook_url


class ConfigHelpersTest(unittest.TestCase):
    def test_derive_webhook_url_prefers_explicit_value(self):
        value = derive_webhook_url(
            "https://example.com",
            "web-production.up.railway.app",
            "https://fallback.example.com",
        )
        self.assertEqual(value, "https://example.com")

    def test_derive_webhook_url_uses_railway_domain_for_placeholder(self):
        value = derive_webhook_url(
            "https://your-domain.com",
            "web-production.up.railway.app",
            "https://fallback.example.com",
        )
        self.assertEqual(value, "https://web-production.up.railway.app")

    def test_derive_internal_api_token_falls_back_from_url_to_bot_token(self):
        value = derive_internal_api_token(
            "https://web-production.up.railway.app/api/internal/data-agent",
            "bot-secret",
        )
        self.assertEqual(value, "bot-secret")

    def test_derive_internal_api_token_keeps_explicit_secret(self):
        value = derive_internal_api_token("shared-secret", "bot-secret")
        self.assertEqual(value, "shared-secret")


if __name__ == "__main__":
    unittest.main()
