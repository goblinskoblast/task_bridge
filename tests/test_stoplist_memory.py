import os
import unittest

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
        )
        self.assertIn("🆕 Добавились", text)
        self.assertIn("✅ Ушли из стоп-листа", text)
        self.assertIn("🔁 Остались с прошлой проверки", text)

    def test_render_stoplist_report_without_history_for_saved_point(self):
        text = point_statistics_service._render_stoplist_report(
            "Сухой Лог, Белинского 40",
            ["Маргарита"],
            {"added": ["Маргарита"], "removed": [], "stayed": []},
            has_history=False,
            is_saved_point=True,
        )
        self.assertIn("🕓 Динамика появится после следующей проверки", text)

    def test_render_stoplist_report_without_saved_point(self):
        text = point_statistics_service._render_stoplist_report(
            "Сухой Лог, Белинского 40",
            ["Маргарита"],
            {"added": ["Маргарита"], "removed": [], "stayed": []},
            has_history=False,
            is_saved_point=False,
        )
        self.assertIn("ℹ️ Чтобы видеть динамику изменений, сохраните эту точку", text)


if __name__ == "__main__":
    unittest.main()
