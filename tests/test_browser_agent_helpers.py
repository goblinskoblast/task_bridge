import os
import tempfile
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.browser_agent import BrowserAgent


class BrowserAgentHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = BrowserAgent()

    def test_classify_page_issue_text_detects_auth_failure(self):
        issue = self.agent._classify_page_issue_text("Неверный пароль. Попробуйте еще раз")
        self.assertEqual(issue, "ОШИБКА_АВТОРИЗАЦИИ: не удалось пройти вход")

    def test_looks_like_auth_screen(self):
        self.assertTrue(self.agent._looks_like_auth_screen("Вход в систему\nЛогин\nПароль"))
        self.assertFalse(self.agent._looks_like_auth_screen("Отчет по продажам за сегодня"))

    def test_parse_delimited_text_handles_csv(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".csv", delete=False) as handle:
            handle.write("col1,col2\nA,B\n")
            path = handle.name

        try:
            parsed = self.agent._parse_delimited_text(path)
        finally:
            os.remove(path)

        self.assertIn("col1\tcol2", parsed)
        self.assertIn("A\tB", parsed)

    def test_build_runtime_diagnostic(self):
        text = self.agent._build_runtime_diagnostic(
            stage="login",
            url="https://example.com/login",
            detail="invalid credentials",
            last_action="click | selector=button[type='submit']",
        )
        self.assertIn("stage=login", text)
        self.assertIn("invalid credentials", text)
        self.assertIn("last_action=", text)


if __name__ == "__main__":
    unittest.main()
