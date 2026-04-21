import os
import unittest
from datetime import datetime

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.models import ConnectedSystem
from data_agent.system_orientation import build_orientation_answer, detect_requested_system_names, wants_system_orientation


class SystemOrientationTest(unittest.TestCase):
    def test_detect_requested_system_names_supports_iiko_and_keeper(self):
        names = detect_requested_system_names("Что умеешь по iiko и keeper?")
        self.assertEqual(names, ["iiko", "keeper"])

    def test_wants_system_orientation_for_connected_systems_phrase(self):
        self.assertTrue(wants_system_orientation("Какие системы у меня подключены?"))

    def test_build_orientation_answer_for_connected_system(self):
        system = ConnectedSystem(
            system_id="sys-1",
            user_id=16,
            system_name="iiko",
            system_title="iiko",
            system_family="restaurant_operations",
            entry_surface="web_portal",
            url="https://sso.iiko.biz/auth",
            login="owner@example.com",
            supports_scan=True,
            supports_points=True,
            supports_monitoring=True,
            capability_labels=["scan", "точки", "мониторинг"],
            orientation_summary="логин -> организация -> точки -> отчёты / операционные разделы",
            next_step_hint="Следом нужен scan структуры iiko и карта сущностей: точки, отчёты, доставка, склад.",
            scan_contract={
                "stage": "scaffold",
                "stage_label": "каркас / scan-first",
                "auth_mode": "sso_web",
                "auth_mode_label": "web SSO",
                "primary_entities": ["организация", "ресторан / точка", "доставка", "склад", "отчёты"],
                "report_sections": ["организации", "точки", "отчёты", "доставка", "склад"],
                "monitor_signals": ["доступность", "меню", "операционка"],
                "reliability_policy": [
                    "сначала строим карту разделов и сущностей",
                    "не выполняем боевые действия до понятного scan",
                    "мониторинг включаем только после привязки точки",
                ],
            },
            created_at=datetime(2026, 4, 21, 17, 0, 0),
        )

        answer = build_orientation_answer("Какие системы у меня подключены?", [system])

        self.assertIn("Сейчас вижу 1 подключённую систему.", answer)
        self.assertIn("1. iiko — ресторанная операционка", answer)
        self.assertIn("стадия: каркас / scan-first", answer)
        self.assertIn("авторизация: web SSO", answer)
        self.assertIn("сущности: организация, ресторан / точка, доставка, склад, отчёты", answer)
        self.assertIn("можем: scan, точки, мониторинг", answer)
        self.assertIn("разделы: организации, точки, отчёты, доставка, склад", answer)
        self.assertIn("сигналы: доступность, меню, операционка", answer)
        self.assertIn("надёжность:", answer)

    def test_build_orientation_answer_for_known_but_not_connected_system(self):
        answer = build_orientation_answer("Что умеешь по keeper?", [])

        self.assertIn("Эта система у вас пока не подключена", answer)
        self.assertIn("1. Keeper — ресторанная операционка", answer)
        self.assertIn("не подключена", answer)
        self.assertIn("стадия: каркас / scan-first", answer)
        self.assertIn("авторизация: web-авторизация", answer)
        self.assertIn("разделы: объекты, кассы, отчёты, меню", answer)


if __name__ == "__main__":
    unittest.main()
