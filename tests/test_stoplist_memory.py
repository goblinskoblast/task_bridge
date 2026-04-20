import os
import unittest
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.point_statistics import point_statistics_service


class StoplistMemoryTest(unittest.TestCase):
    def test_extract_stoplist_items_prefers_explicit_items(self):
        result = {
            "status": "ok",
            "items": ["Пепперони", "Маргарита"],
            "report_text": "Точка: Тест\nСтоп-лист:\n- Другое",
        }
        self.assertEqual(
            point_statistics_service._extract_stoplist_items(result),
            ["Пепперони", "Маргарита"],
        )

    def test_compute_stoplist_delta(self):
        delta = point_statistics_service._compute_stoplist_delta(
            ["Пепперони", "Маргарита"],
            ["Маргарита", "Четыре сыра"],
        )
        self.assertEqual(delta["added"], ["Четыре сыра"])
        self.assertEqual(delta["removed"], ["Пепперони"])
        self.assertEqual(delta["stayed"], ["Маргарита"])

    def test_matches_saved_point_by_external_slug(self):
        point = SimpleNamespace(
            city="Верхний Уфалей",
            address="Ленина 147",
            display_name="Верхний Уфалей, Ленина 147",
            external_point_key="ufaley",
        )
        self.assertTrue(
            point_statistics_service._matches_saved_point(
                point,
                target_slug="ufaley",
                target_city="верхний уфалей",
                target_address="ленина 147",
                normalized_target_display=point_statistics_service._normalize_point_name("Верхний Уфалей, Ленина 147"),
            )
        )

    def test_build_stoplist_item_history_days_tracks_current_and_removed_items(self):
        snapshots = [
            SimpleNamespace(snapshot_at=datetime(2026, 4, 18, 8, 0), stoplist_items_json=["Маргарита", "Пепперони"]),
            SimpleNamespace(snapshot_at=datetime(2026, 4, 19, 8, 0), stoplist_items_json=["Маргарита", "Пепперони"]),
        ]

        history = point_statistics_service._build_stoplist_item_history_days(
            snapshots,
            ["Маргарита", "Четыре сыра"],
            as_of=datetime(2026, 4, 20, 8, 0),
        )

        self.assertEqual(history["current"]["Маргарита"], 3)
        self.assertEqual(history["current"]["Четыре сыра"], 1)
        self.assertEqual(history["removed"]["Пепперони"], 2)

    def test_render_stoplist_report_with_history(self):
        text = point_statistics_service._render_stoplist_report(
            "Сухой Лог, Белинского 40",
            ["Маргарита", "Четыре сыра"],
            {
                "added": ["Четыре сыра"],
                "removed": ["Пепперони"],
                "stayed": ["Маргарита"],
            },
            has_history=True,
            is_saved_point=True,
            current_age_days={"Маргарита": 3, "Четыре сыра": 1},
            removed_age_days={"Пепперони": 2},
        )
        self.assertIn("🆕 Новые в стопе: 1", text)
        self.assertIn("1. Четыре сыра — в стопе 1 день", text)
        self.assertIn("🟠 Уже в стопе: 1", text)
        self.assertIn("1. Маргарита — в стопе 3 дня", text)
        self.assertIn("🟢 Ушли из стопа: 1", text)
        self.assertIn("1. Пепперони — была в стопе 2 дня", text)

    def test_render_stoplist_report_without_history_for_saved_point(self):
        text = point_statistics_service._render_stoplist_report(
            "Сухой Лог, Белинского 40",
            ["Маргарита"],
            {"added": ["Маргарита"], "removed": [], "stayed": []},
            has_history=False,
            is_saved_point=True,
        )
        self.assertIn("🟠 Сейчас в стопе: 1", text)
        self.assertIn("1. Маргарита", text)
        self.assertIn("🕓 Разделю позиции на новые и ушедшие", text)

    def test_render_stoplist_report_does_not_truncate_items(self):
        current_items = [f"Позиция {index}" for index in range(1, 28)]
        removed_items = [f"Ушла {index}" for index in range(1, 4)]
        text = point_statistics_service._render_stoplist_report(
            "Верхний Уфалей, Ленина 147",
            current_items,
            {
                "added": current_items[20:],
                "removed": removed_items,
                "stayed": current_items[:20],
            },
            has_history=True,
            is_saved_point=True,
            current_age_days={item: 4 for item in current_items[:20]} | {item: 1 for item in current_items[20:]},
            removed_age_days={item: 2 for item in removed_items},
        )
        self.assertIn("20. Позиция 20 — в стопе 4 дня", text)
        self.assertIn("7. Позиция 27 — в стопе 1 день", text)
        self.assertIn("3. Ушла 3 — была в стопе 2 дня", text)
        self.assertNotIn("… и ещё", text)

    def test_render_stoplist_report_without_saved_point(self):
        text = point_statistics_service._render_stoplist_report(
            "Сухой Лог, Белинского 40",
            ["Маргарита"],
            {"added": ["Маргарита"], "removed": [], "stayed": []},
            has_history=False,
            is_saved_point=False,
        )
        self.assertIn("🟠 Сейчас в стопе: 1", text)
        self.assertIn("ℹ️ Чтобы видеть новые позиции, ушедшие позиции и дни в стопе", text)


if __name__ == "__main__":
    unittest.main()
