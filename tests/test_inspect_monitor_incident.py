import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from scripts.inspect_monitor_incident import _compact_result, _profile_payload, _safe_text


class InspectMonitorIncidentTest(unittest.TestCase):
    def test_safe_text_replaces_mojibake(self):
        self.assertEqual(_safe_text("????????"), "corrupted_text")

    def test_compact_result_hides_diagnostics_by_default(self):
        result = _compact_result(
            {
                "status": "ok",
                "has_red_flags": False,
                "period_hint": "за последние 3 часа",
                "report_text": "Отчёт готов",
                "diagnostics": {
                    "stage": "period_selection",
                    "visible_period_controls": ["3", "6"],
                    "styled_cell_samples": [{"value": "huge"}],
                },
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["diagnostics_stage"], "period_selection")
        self.assertNotIn("last_result_json", result)
        self.assertNotIn("diagnostics", result)

    def test_compact_result_can_include_full_json_explicitly(self):
        payload = {"status": "ok", "diagnostics": {"stage": "report_read"}}

        result = _compact_result(payload, include_result_json=True)

        self.assertIs(result["last_result_json"], payload)

    def test_profile_payload_uses_safe_chat_labels(self):
        profile = SimpleNamespace(
            default_report_chat_id=-1001,
            default_report_chat_title="????????",
            blanks_report_chat_id=-1002,
            blanks_report_chat_title="Бланки",
            stoplist_report_chat_id=-1003,
            stoplist_report_chat_title=None,
        )

        result = _profile_payload(profile)

        self.assertEqual(result["default_report_chat_label"], "привязанный чат")
        self.assertEqual(result["blanks_report_chat_label"], "чат «Бланки»")
        self.assertEqual(result["stoplist_report_chat_label"], "привязанный чат")


if __name__ == "__main__":
    unittest.main()
