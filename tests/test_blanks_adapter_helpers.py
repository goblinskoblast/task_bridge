import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from data_agent.adapters.italian_pizza_portal_adapter import ItalianPizzaPortalAdapter


class BlanksAdapterHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ItalianPizzaPortalAdapter()

    def test_detect_terminal_issue_for_auth_failure(self):
        issue = self.adapter._detect_terminal_issue(
            "\u041e\u0448\u0438\u0431\u043a\u0430: \u043d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u043f\u0430\u0440\u043e\u043b\u044c"
        )
        self.assertEqual(
            issue,
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0432\u043e\u0439\u0442\u0438 \u0432 \u043f\u043e\u0440\u0442\u0430\u043b: "
            "\u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u043b\u043e\u0433\u0438\u043d \u0438 \u043f\u0430\u0440\u043e\u043b\u044c."
        )

    def test_detect_terminal_issue_for_access_denied(self):
        issue = self.adapter._detect_terminal_issue("403 forbidden")
        self.assertEqual(issue, "\u041f\u043e\u0440\u0442\u0430\u043b \u0432\u0435\u0440\u043d\u0443\u043b \u043e\u0442\u043a\u0430\u0437 \u0432 \u0434\u043e\u0441\u0442\u0443\u043f\u0435.")

    def test_looks_like_login_page(self):
        self.assertTrue(
            self.adapter._looks_like_login_page(
                "\u041b\u043e\u0433\u0438\u043d\n\u041f\u0430\u0440\u043e\u043b\u044c\n\u0412\u043e\u0439\u0442\u0438"
            )
        )
        self.assertFalse(
            self.adapter._looks_like_login_page(
                "\u041e\u0442\u0447\u0435\u0442 \u043f\u043e \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430\u043c\n"
                "\u041a\u0440\u0430\u0441\u043d\u044b\u0445 \u0431\u043b\u0430\u043d\u043a\u043e\u0432 \u043d\u0435\u0442"
            )
        )

    def test_contains_report_context(self):
        self.assertTrue(
            self.adapter._contains_report_context(
                "\u041e\u0442\u0447\u0435\u0442 \u043f\u043e \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430\u043c\n"
                "\u0415\u0441\u0442\u044c \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u0438\u044f \u043f\u043e \u043b\u0438\u043c\u0438\u0442\u0443"
            )
        )
        self.assertFalse(
            self.adapter._contains_report_context(
                "\u0413\u043b\u0430\u0432\u043d\u0430\u044f\n\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438\n\u041f\u0440\u043e\u0444\u0438\u043b\u044c"
            )
        )

    def test_point_match_score_prefers_relevant_point_labels(self):
        strong = self.adapter._point_match_score(
            "Upper Ufaley Lenina 147",
            "Upper Ufaley, Lenina 147",
        )
        weak = self.adapter._point_match_score(
            "Ekaterinburg Malysheva 5",
            "Upper Ufaley, Lenina 147",
        )
        self.assertGreater(strong, weak)

    def test_point_specificity_prefers_full_row_with_address(self):
        detailed = self.adapter._point_specificity_score(
            "Artemovsky (1) Gagarina, 2A",
            "Artemovsky, Gagarina 2a",
        )
        short = self.adapter._point_specificity_score(
            "Artemovsky (1)",
            "Artemovsky, Gagarina 2a",
        )
        self.assertGreater(detailed, short)

    def test_point_address_variants_include_nested_sidebar_label(self):
        variants = self.adapter._point_address_variants("Testcity, Main 2a")
        self.assertIn("Main 2a", variants)
        self.assertIn("Main, 2a", variants)

    def test_point_group_variants_include_sidebar_bucket(self):
        variants = self.adapter._point_group_variants("Testcity, Main 2a")
        self.assertIn("Testcity", variants)
        self.assertIn("Testcity (1)", variants)

    def test_point_menu_looks_open_for_multiple_point_rows(self):
        self.assertTrue(
            self.adapter._point_menu_looks_open(
                [
                    "Artemovsky (1) Gagarina, 2A",
                    "Asbest (1) Lenina, 5",
                    "Upper Ufaley (1) Lenina, 147",
                ]
            )
        )
        self.assertFalse(self.adapter._point_menu_looks_open(["Artemovsky (1) Gagarina, 2A"]))

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

    def test_point_header_matches_requested_point(self):
        self.assertTrue(
            self.adapter._point_header_matches_requested_point(
                "Operator\nTestcity, Main, 2A\nBlank report",
                "Testcity, Main 2a",
            )
        )
        self.assertFalse(
            self.adapter._point_header_matches_requested_point(
                "Operator\nOthercity, Side, 12A\nBlank report",
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
            "Test point",
            "\n".join(
                [
                    "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
                    "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438",
                    "\u041e\u0442\u0447\u0435\u0442 \u043f\u043e \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430\u043c",
                    "\u041a\u0440\u0430\u0441\u043d\u044b\u0439 \u0431\u043b\u0430\u043d\u043a \u043f\u043e \u0441\u0442\u0440\u043e\u043a\u0435 12",
                    "\u041b\u0438\u043c\u0438\u0442 \u043f\u0440\u0435\u0432\u044b\u0448\u0435\u043d",
                ]
            ),
        )
        self.assertTrue(has_red_flags)
        self.assertNotIn("\u0413\u043b\u0430\u0432\u043d\u0430\u044f", report_text)
        self.assertIn("\u041a\u0440\u0430\u0441\u043d\u044b\u0439 \u0431\u043b\u0430\u043d\u043a", report_text)

    def test_build_failed_result_marks_status_failed(self):
        result = self.adapter._build_failed_result(
            "Test point",
            "Portal denied access.",
            "current blank",
            diagnostics={"stage": "login_submit", "point_selected": False},
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["has_red_flags"])
        self.assertIn("Portal denied access.", result["report_text"])
        self.assertEqual(result["diagnostics"]["stage"], "login_submit")
        self.assertFalse(result["diagnostics"]["point_selected"])

    def test_period_candidates_support_six_hours(self):
        candidates = self.adapter._period_candidates(
            "\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 6 \u0447\u0430\u0441\u043e\u0432"
        )
        self.assertIn("6 \u0447\u0430\u0441\u043e\u0432", candidates)

    def test_build_period_candidates_do_not_include_ambiguous_numeric_only_values(self):
        candidates = self.adapter._period_candidates(
            "\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 6 \u0447\u0430\u0441\u043e\u0432"
        )
        self.assertNotIn("6", candidates)

    def test_blank_hour_value_extracts_supported_numeric_chip(self):
        self.assertEqual(
            self.adapter._blank_hour_value("\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 3 \u0447\u0430\u0441\u0430"),
            "3",
        )
        self.assertEqual(
            self.adapter._blank_hour_value("\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 12 \u0447\u0430\u0441\u043e\u0432"),
            "12",
        )
        self.assertIsNone(
            self.adapter._blank_hour_value("\u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u0431\u043b\u0430\u043d\u043a")
        )

    def test_rolling_blank_hours_extracts_requested_window(self):
        self.assertEqual(
            self.adapter._rolling_blank_hours("\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 12 \u0447\u0430\u0441\u043e\u0432"),
            12,
        )
        self.assertEqual(
            self.adapter._rolling_blank_hours("\u0441\u0443\u0442\u043a\u0438"),
            24,
        )
        self.assertIsNone(
            self.adapter._rolling_blank_hours("\u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u0431\u043b\u0430\u043d\u043a")
        )

    def test_blank_hour_scan_values_cover_last_three_hours(self):
        values = self.adapter._blank_hour_scan_values(
            "\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 3 \u0447\u0430\u0441\u0430",
            reference_time=datetime(2026, 4, 7, 22, 30),
        )
        self.assertEqual(values, ["18", "21"])

    def test_blank_hour_scan_values_cover_last_twelve_hours(self):
        values = self.adapter._blank_hour_scan_values(
            "\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 12 \u0447\u0430\u0441\u043e\u0432",
            reference_time=datetime(2026, 4, 7, 22, 30),
        )
        self.assertEqual(values, ["9", "12", "15", "18", "21"])

    def test_build_blank_report_from_signals_summarizes_red_zones(self):
        report_text, has_red_flags = self.adapter._build_blank_report_from_signals(
            point_name="Test point",
            period_hint="\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 12 \u0447\u0430\u0441\u043e\u0432",
            signals=[
                {
                    "service": "\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
                    "time_range": "16:45 - 17:00",
                    "column": "\u0417\u0430\u043a\u0443\u0441\u043a\u0438",
                    "rows": [
                        {"row_label": "\u041c\u0430\u043a\u0441", "value": "15"},
                        {"row_label": "\u041f\u0440\u0438\u043d\u044f\u0442\u043e", "value": "0"},
                    ],
                }
            ],
        )
        self.assertTrue(has_red_flags)
        self.assertIn("\U0001F534 \u0421\u0442\u0430\u0442\u0443\u0441", report_text)
        self.assertIn("\U0001F534 1.", report_text)
        self.assertIn("16:45 - 17:00", report_text)
        self.assertIn("\u0417\u0430\u043a\u0443\u0441\u043a\u0438", report_text)
        self.assertIn("\u041f\u0440\u0438\u043d\u044f\u0442\u043e: 0", report_text)

    def test_build_blank_report_without_signals_marks_green_status(self):
        report_text, has_red_flags = self.adapter._build_blank_report_from_signals(
            point_name="Test point",
            period_hint="\u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u0431\u043b\u0430\u043d\u043a",
            signals=[],
        )
        self.assertFalse(has_red_flags)
        self.assertIn("\u2705 \u0421\u0442\u0430\u0442\u0443\u0441", report_text)
        self.assertIn("\U0001F4CD \u0422\u043e\u0447\u043a\u0430", report_text)

    def test_filter_red_blank_signals_ignores_warning_only_rows(self):
        filtered = self.adapter._filter_red_blank_signals(
            [
                {
                    "service": "\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
                    "time_range": "18:00 - 18:15",
                    "column": "\u041f\u0438\u0446\u0446\u0430",
                    "rows": [
                        {
                            "row_label": "\u041e\u0441\u0442\u0430\u0442\u043e\u043a",
                            "value": "1",
                            "class_name": "blank-cell warning-state",
                            "data_cy": "capacity-warning",
                            "background_color": "rgb(255, 244, 179)",
                            "text_color": "rgb(40, 40, 40)",
                            "border_color": "rgb(255, 224, 102)",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(filtered, [])

    def test_filter_red_blank_signals_ignores_limit_state_without_red_style(self):
        filtered = self.adapter._filter_red_blank_signals(
            [
                {
                    "service": "\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
                    "time_range": "18:00 - 18:15",
                    "column": "\u041f\u0438\u0446\u0446\u0430",
                    "rows": [
                        {
                            "row_label": "\u041f\u0440\u0438\u043d\u044f\u0442\u043e",
                            "value": "0",
                            "class_name": "blank-cell limit-state",
                            "data_cy": "capacity-limit",
                            "background_color": "rgb(255, 244, 179)",
                            "text_color": "rgb(40, 40, 40)",
                            "border_color": "rgb(255, 224, 102)",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(filtered, [])

    def test_filter_red_blank_signals_keeps_inferred_breach_rows(self):
        filtered = self.adapter._filter_red_blank_signals(
            [
                {
                    "service": "\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
                    "time_range": "18:00 - 18:15",
                    "column": "\u041f\u0438\u0446\u0446\u0430",
                    "rows": [
                        {
                            "row_label": "\u041c\u0430\u043a\u0441",
                            "value": "4",
                            "inferred_rule": "accepted_gt_max",
                        },
                        {
                            "row_label": "\u041f\u0440\u0438\u043d\u044f\u0442\u043e",
                            "value": "7",
                            "inferred_rule": "accepted_gt_max",
                        },
                    ],
                }
            ]
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(filtered[0]["rows"]), 2)

    def test_build_period_help_message_uses_visible_controls(self):
        message = self.adapter._build_period_help_message(
            "\u0437\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 6 \u0447\u0430\u0441\u043e\u0432",
            ["3 \u0447\u0430\u0441\u0430", "12 \u0447\u0430\u0441\u043e\u0432", "\u0421\u0443\u0442\u043a\u0438"],
        )
        self.assertIn("6 \u0447\u0430\u0441\u043e\u0432", message)
        self.assertIn("3 \u0447\u0430\u0441\u0430", message)
        self.assertIn("12 \u0447\u0430\u0441\u043e\u0432", message)

    def test_point_selection_confirmed_for_address_specific_match(self):
        point_result = {
            "selected": True,
            "matched_point": "Lenina, 147",
            "visible_point_controls": ["Upper Ufaley", "Lenina, 147"],
            "point_menu_collapsed": False,
        }
        self.assertTrue(
            self.adapter._point_selection_confirmed(
                point_result,
                "Blank overload report\nHome",
                "Upper Ufaley, Lenina 147",
            )
        )

    def test_point_selection_confirmed_when_body_mentions_point(self):
        point_result = {
            "selected": False,
            "matched_point": None,
            "visible_point_controls": ["Home", "Blank overload report"],
            "point_menu_collapsed": False,
        }
        self.assertTrue(
            self.adapter._point_selection_confirmed(
                point_result,
                "Operator\nUpper Ufaley, Lenina 147\nBlank overload report",
                "Upper Ufaley, Lenina 147",
            )
        )

    def test_point_selection_not_confirmed_for_city_only_match_with_open_menu(self):
        point_result = {
            "selected": True,
            "matched_point": "Upper Ufaley",
            "visible_point_controls": [
                "Upper Ufaley (1) Lenina, 147",
                "Yekaterinburg (1) Sulimova, 31A",
                "Asbest (1) Leningradskaya, 26/2",
            ],
            "point_menu_collapsed": False,
        }
        self.assertFalse(
            self.adapter._point_selection_confirmed(
                point_result,
                "Home\nBlank overload report",
                "Upper Ufaley, Lenina 147",
            )
        )

class BlanksAdapterAsyncHelpersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.adapter = ItalianPizzaPortalAdapter()

    async def test_trigger_login_submit_uses_enter_after_retry_click(self):
        button = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            click=AsyncMock(),
        )
        password = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            press=AsyncMock(),
        )

        class Locator:
            def __init__(self, item=None):
                self.first = item

            async def count(self):
                return 1 if self.first is not None else 0

        class Page:
            def locator(self, selector):
                if selector == "button[type='submit']":
                    return Locator(button)
                if selector == "input[type='password']":
                    return Locator(password)
                return Locator()

        result = await self.adapter._trigger_login_submit(Page(), use_force=True, use_enter=True)

        self.assertTrue(result)
        button.click.assert_awaited_once_with(timeout=3500, force=True)
        password.press.assert_awaited_once_with("Enter")

    async def test_submit_login_and_wait_retries_after_staying_on_login_page(self):
        page = object()
        with patch.object(self.adapter, "_trigger_login_submit", AsyncMock(return_value=True)) as mocked_submit:
            with patch.object(
                self.adapter,
                "_wait_for_post_login_state",
                AsyncMock(side_effect=[("login_page", "Логин"), ("ok", "Портал")]),
            ) as mocked_wait:
                state, text = await self.adapter._submit_login_and_wait(page)

        self.assertEqual((state, text), ("ok", "Портал"))
        self.assertEqual(mocked_submit.await_count, 2)
        self.assertEqual(mocked_wait.await_count, 2)
        self.assertFalse(mocked_submit.await_args_list[0].kwargs["use_force"])
        self.assertFalse(mocked_submit.await_args_list[0].kwargs["use_enter"])
        self.assertTrue(mocked_submit.await_args_list[1].kwargs["use_force"])
        self.assertTrue(mocked_submit.await_args_list[1].kwargs["use_enter"])

    async def test_load_report_context_retries_until_period_controls_appear(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(
            self.adapter,
            "_open_report_context_if_needed",
            AsyncMock(
                side_effect=[
                    {
                        "body": "Главная\nПрофиль",
                        "visible_period_controls": [],
                        "visible_report_controls": [],
                        "route_label": None,
                    },
                    {
                        "body": "Бланк загрузки\nОтчет по перегрузкам",
                        "visible_period_controls": ["3", "6"],
                        "visible_report_controls": ["Бланк загрузки"],
                        "route_label": "Бланк загрузки",
                    },
                ]
            ),
        ) as mocked_context:
            result = await self.adapter._load_report_context(page, "Сухой Лог, Белинского 40")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["visible_period_controls"], ["3", "6"])
        self.assertEqual(mocked_context.await_count, 2)
        page.wait_for_timeout.assert_awaited_once()

    async def test_open_report_context_waits_for_same_route_to_render(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(
            self.adapter,
            "_capture_report_context_snapshot",
            AsyncMock(
                side_effect=[
                    {
                        "body": "Главная\nПрофиль",
                        "visible_period_controls": [],
                        "visible_report_controls": [],
                        "route_label": None,
                    },
                    {
                        "body": "Главная\nЗагрузка...",
                        "visible_period_controls": [],
                        "visible_report_controls": ["Бланк загрузки"],
                        "route_label": "Бланк загрузки",
                    },
                    {
                        "body": "Бланк загрузки\nОтчет по перегрузкам",
                        "visible_period_controls": ["3", "6"],
                        "visible_report_controls": ["Бланк загрузки"],
                        "route_label": "Бланк загрузки",
                    },
                ]
            ),
        ) as mocked_snapshot:
            with patch.object(
                self.adapter,
                "_click_visible_text_candidate",
                AsyncMock(return_value="Бланк загрузки"),
            ) as mocked_click:
                with patch.object(
                    self.adapter,
                    "_ensure_point_menu_collapsed",
                    AsyncMock(return_value=(True, [])),
                ) as mocked_collapse:
                    result = await self.adapter._open_report_context_if_needed(page, "Сухой Лог, Белинского 40")

        self.assertEqual(result["route_label"], "Бланк загрузки")
        self.assertEqual(result["visible_period_controls"], ["3", "6"])
        self.assertEqual(mocked_snapshot.await_count, 3)
        mocked_click.assert_awaited_once()
        mocked_collapse.assert_awaited_once()
        self.assertGreaterEqual(page.wait_for_timeout.await_count, 2)

    async def test_click_blank_hour_chip_retries_after_transient_failure(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(
            self.adapter,
            "_click_blank_hour_chip_once",
            AsyncMock(side_effect=[False, True]),
        ) as mocked_click:
            result = await self.adapter._click_blank_hour_chip(page, "3")

        self.assertTrue(result)
        self.assertEqual(mocked_click.await_count, 2)
        page.wait_for_timeout.assert_awaited_once()

    async def test_click_blank_hour_chip_confirms_disabled_chip_applied_to_table(self):
        button = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            get_attribute=AsyncMock(return_value="Mui-disabled"),
            is_disabled=AsyncMock(return_value=True),
            click=AsyncMock(),
        )

        class Locator:
            def __init__(self, item=None):
                self.first = item

            async def count(self):
                return 1 if self.first is not None else 0

            def nth(self, index):
                return self.first

        class Page:
            def locator(self, selector):
                if selector == "button[data-cy='hour-3']":
                    return Locator(button)
                return Locator()

        page = Page()
        with patch.object(
            self.adapter,
            "_wait_for_blank_hour_applied",
            AsyncMock(return_value=True),
        ) as mocked_wait:
            result = await self.adapter._click_blank_hour_chip_once(page, "3")

        self.assertTrue(result)
        mocked_wait.assert_awaited_once()
        self.assertIs(mocked_wait.await_args.args[0], page)
        self.assertEqual(mocked_wait.await_args.args[1], "3")
        self.assertEqual(mocked_wait.await_args.kwargs["timeout_ms"], 3500)
        button.click.assert_not_awaited()

    async def test_click_blank_hour_chip_rejects_disabled_chip_when_table_is_stale(self):
        button = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            get_attribute=AsyncMock(return_value="Mui-disabled"),
            is_disabled=AsyncMock(return_value=True),
            click=AsyncMock(),
        )

        class Locator:
            def __init__(self, item=None):
                self.first = item

            async def count(self):
                return 1 if self.first is not None else 0

        class Page:
            def locator(self, selector):
                if selector == "button[data-cy='hour-3']":
                    return Locator(button)
                return Locator()

        with patch.object(
            self.adapter,
            "_wait_for_blank_hour_applied",
            AsyncMock(return_value=False),
        ) as mocked_wait:
            result = await self.adapter._click_blank_hour_chip_once(Page(), "3")

        self.assertFalse(result)
        mocked_wait.assert_awaited_once()
        button.click.assert_not_awaited()

    async def test_wait_for_blank_hour_applied_accepts_matching_slot_without_active_button(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(self.adapter, "_active_blank_hour_value", AsyncMock(return_value=None)):
            with patch.object(self.adapter, "_first_blank_slot", AsyncMock(return_value="2026-04-19T03:00")):
                result = await self.adapter._wait_for_blank_hour_applied(page, "3")

        self.assertTrue(result)
        page.wait_for_timeout.assert_not_awaited()

    async def test_wait_for_blank_hour_applied_accepts_zero_padded_active_hour(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(self.adapter, "_active_blank_hour_value", AsyncMock(return_value="03")):
            with patch.object(self.adapter, "_first_blank_slot", AsyncMock(return_value=None)):
                result = await self.adapter._wait_for_blank_hour_applied(page, "3")

        self.assertTrue(result)
        page.wait_for_timeout.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
