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

    def test_looks_like_login_page(self):
        self.assertTrue(self.adapter._looks_like_login_page("Логин\nПароль\nВойти"))
        self.assertFalse(self.adapter._looks_like_login_page("Отчет по перегрузкам\nКрасных бланков нет"))

    def test_contains_report_context(self):
        self.assertTrue(self.adapter._contains_report_context("Отчет по перегрузкам\nЕсть отклонения по лимиту"))
        self.assertFalse(self.adapter._contains_report_context("Главная\nНастройки\nПрофиль"))

    def test_point_match_score_prefers_relevant_point_labels(self):
        strong = self.adapter._point_match_score("Верхний Уфалей Ленина 147", "Верхний Уфалей, Ленина 147")
        weak = self.adapter._point_match_score("Екатеринбург Малышева 5", "Верхний Уфалей, Ленина 147")
        self.assertGreater(strong, weak)

    def test_point_specificity_prefers_full_row_with_address(self):
        detailed = self.adapter._point_specificity_score("Артемовский (1) Гагарина, 2А", "Артёмовский, Гагарина 2а")
        short = self.adapter._point_specificity_score("Артемовский (1)", "Артёмовский, Гагарина 2а")
        self.assertGreater(detailed, short)

    def test_point_menu_looks_open_for_multiple_point_rows(self):
        self.assertTrue(
            self.adapter._point_menu_looks_open(
                [
                    "Артемовский (1) Гагарина, 2А",
                    "Асбест (1) Ленина, 5",
                    "Верхний Уфалей (1) Ленина, 147",
                ]
            )
        )
        self.assertFalse(self.adapter._point_menu_looks_open(["Артемовский (1) Гагарина, 2А"]))

    def test_body_mentions_requested_point_by_address_tokens(self):
        self.assertTrue(
            self.adapter._body_mentions_requested_point(
                "Point: Testcity\nDelivery address: Main, 2A",
                "Testcity, Main 2a",
            )
        )
        self.assertFalse(
            self.adapter._body_mentions_requested_point(
                "Point: Othercity\nDelivery address: Side, 12a",
                "Testcity, Main 2a",
            )
        )

    def test_extract_point_specific_body_keeps_only_matching_lines(self):
        body, matched = self.adapter._extract_point_specific_body(
            "\n".join(
                [
                    "Report overloads",
                    "Othercity, Side, 12a",
                    "Testcity, Main, 2A",
                ]
            ),
            "Testcity, Main 2a",
        )
        self.assertTrue(matched)
        self.assertIn("Testcity, Main, 2A", body)
        self.assertNotIn("Othercity", body)

    def test_normalize_report_filters_navigation_noise(self):
        report_text, has_red_flags = self.adapter._normalize_report(
            "Тестовая точка",
            "\n".join(
                [
                    "Главная",
                    "Настройки",
                    "Отчет по перегрузкам",
                    "Красный бланк по строке 12",
                    "Лимит превышен",
                ]
            ),
        )
        self.assertTrue(has_red_flags)
        self.assertNotIn("Главная", report_text)
        self.assertIn("Красный бланк", report_text)

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

    def test_period_candidates_support_six_hours(self):
        candidates = self.adapter._period_candidates("за последние 6 часов")
        self.assertIn("6 часов", candidates)

    def test_build_period_candidates_do_not_include_ambiguous_numeric_only_values(self):
        candidates = self.adapter._period_candidates("за последние 6 часов")
        self.assertNotIn("6", candidates)

    def test_build_period_help_message_uses_visible_controls(self):
        message = self.adapter._build_period_help_message("за последние 6 часов", ["3 часа", "12 часов", "Сутки"])
        self.assertIn("6 часов", message)
        self.assertIn("3 часа", message)
        self.assertIn("12 часов", message)


if __name__ == "__main__":
    unittest.main()
