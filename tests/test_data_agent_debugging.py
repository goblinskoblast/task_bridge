import unittest

from data_agent.debugging import build_debug_artifacts, derive_response_status


class DataAgentDebuggingTest(unittest.TestCase):
    def test_derive_response_status_marks_failed(self):
        status = derive_response_status(
            {
                "blanks_tool": {
                    "status": "failed",
                    "message": "Login failed",
                }
            }
        )
        self.assertEqual(status, "failed")

    def test_derive_response_status_marks_completed_for_ok(self):
        status = derive_response_status(
            {
                "stoplist_tool": {
                    "status": "ok",
                    "items": [],
                }
            }
        )
        self.assertEqual(status, "completed")

    def test_derive_response_status_marks_not_configured_as_failed(self):
        status = derive_response_status(
            {
                "review_tool": {
                    "status": "not_configured",
                    "message": "Не задан REVIEWS_SHEET_URL",
                }
            }
        )
        self.assertEqual(status, "failed")

    def test_build_debug_artifacts_includes_stage_and_url(self):
        payload, summary = build_debug_artifacts(
            trace_id="trace-123",
            scenario="blanks_report",
            status="failed",
            selected_tools=["blanks_tool"],
            tool_results={
                "blanks_tool": {
                    "status": "failed",
                    "message": "Portal rejected login",
                    "diagnostics": {
                        "stage": "login_submit",
                        "url": "https://portal.example.com/login",
                    },
                }
            },
        )

        self.assertEqual(payload["tools"][0]["stage"], "login_submit")
        self.assertIn("Trace: trace-123", summary)
        self.assertIn("Этап: login_submit", summary)
        self.assertIn("portal.example.com/login", summary)

    def test_build_debug_artifacts_includes_selection_diagnostics(self):
        payload, summary = build_debug_artifacts(
            trace_id="trace-789",
            scenario="stoplist_report",
            status="failed",
            selected_tools=["stoplist_tool"],
            tool_results={
                "stoplist_tool": {
                    "status": "failed",
                    "message": "Не удалось подтвердить выбор точки.",
                    "diagnostics": {
                        "stage": "confirm_point",
                        "url": "https://pizza.example.com/store",
                        "point_selected": False,
                        "address_filled": False,
                        "products_found": 0,
                    },
                }
            },
        )

        self.assertFalse(payload["tools"][0]["point_selected"])
        self.assertFalse(payload["tools"][0]["address_filled"])
        self.assertEqual(payload["tools"][0]["products_found"], 0)
        self.assertIn("Точка: не подтверждена", summary)
        self.assertIn("Адрес: не удалось заполнить", summary)
        self.assertIn("Найдено позиций: 0", summary)

    def test_build_debug_artifacts_keeps_visible_point_controls_in_payload(self):
        payload, _ = build_debug_artifacts(
            trace_id="trace-900",
            scenario="blanks_report",
            status="failed",
            selected_tools=["blanks_tool"],
            tool_results={
                "blanks_tool": {
                    "status": "failed",
                    "message": "Не удалось выбрать нужную точку на портале.",
                    "diagnostics": {
                        "stage": "point_selection",
                        "url": "https://tochka.example.com/#/",
                        "visible_point_controls": ["Выберите точку", "Верхний Уфалей", "Екатеринбург"],
                        "point_candidates": ["Верхний Уфалей, Ленина 147", "Верхний Уфалей", "Ленина 147"],
                        "page_excerpt": "выберите точку верхний уфалей екатеринбург",
                    },
                }
            },
        )

        tool = payload["tools"][0]
        self.assertEqual(tool["visible_point_controls"][0], "Выберите точку")
        self.assertIn("Верхний Уфалей", tool["point_candidates"])
        self.assertIn("выберите точку", tool["page_excerpt"])

    def test_build_debug_artifacts_uses_failed_target_error(self):
        payload, summary = build_debug_artifacts(
            trace_id="trace-456",
            scenario="reviews_report",
            status="failed",
            selected_tools=["review_tool"],
            tool_results={
                "review_tool": {
                    "status": "failed",
                    "targets": [
                        {
                            "target": "Екатеринбург, Малышева 5",
                            "status": "error",
                            "error": "Captcha detected",
                            "url": "https://maps.example.com",
                        }
                    ],
                }
            },
        )

        self.assertEqual(payload["tools"][0]["target"], "Екатеринбург, Малышева 5")
        self.assertIn("Captcha detected", summary)
        self.assertIn("Цель: Екатеринбург, Малышева 5", summary)


    def test_build_debug_artifacts_keeps_point_opener_and_query(self):
        payload, _ = build_debug_artifacts(
            trace_id="trace-901",
            scenario="blanks_report",
            status="failed",
            selected_tools=["blanks_tool"],
            tool_results={
                "blanks_tool": {
                    "status": "failed",
                    "message": "Point not selected",
                    "diagnostics": {
                        "stage": "point_selection",
                        "url": "https://tochka.example.com/#/",
                        "point_menu_opener": "Выбрать точку продаж",
                        "point_search_query": "Верхний Уфалей",
                    },
                }
            },
        )

        tool = payload["tools"][0]
        self.assertEqual(tool["point_menu_opener"], "Выбрать точку продаж")
        self.assertEqual(tool["point_search_query"], "Верхний Уфалей")


if __name__ == "__main__":
    unittest.main()
