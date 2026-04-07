import unittest

from data_agent.adapters.italian_pizza_portal_adapter import ItalianPizzaPortalAdapter


class BlanksAdapterHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ItalianPizzaPortalAdapter()

    def test_detect_terminal_issue_for_auth_failure(self):
        issue = self.adapter._detect_terminal_issue("Ошибка: неверный пароль")
        self.assertEqual(issue, "Не удалось войти в портал: проверьте логин и пароль.")

    def test_detect_terminal_issue_for_access_denied(self):
        issue = self.adapter._detect_terminal_issue("403 forbidden")
        self.assertEqual(issue, "Портал вернул отказ в доступе.")

    def test_build_failed_result_marks_status_failed(self):
        result = self.adapter._build_failed_result(
            "Тестовая точка",
            "Портал вернул отказ в доступе.",
            "текущий бланк",
            diagnostics={"stage": "login_submit", "point_selected": False},
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["has_red_flags"])
        self.assertIn("Портал вернул отказ", result["report_text"])
        self.assertEqual(result["diagnostics"]["stage"], "login_submit")
        self.assertFalse(result["diagnostics"]["point_selected"])


if __name__ == "__main__":
    unittest.main()
