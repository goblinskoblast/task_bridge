import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from data_agent.review_analytics import (
    ItalianPizzaSheetAnalyticsProvider,
    ReviewAnalyticsPeriod,
    review_analytics_coordinator,
)
from data_agent.review_report import ReviewReportService


class ItalianPizzaSheetAnalyticsProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_report_uses_latest_weekly_column(self):
        provider = ItalianPizzaSheetAnalyticsProvider(["https://example.com/sheet"])
        rows = [
            ["", "", "Полевской", "", "05.01.2026", "01.01.2026", "02.02.2026", "01.02.2026"],
            ["", "", "", "", "11.01.2026", "31.01.2026 23:59:59", "08.02.2026", "28.02.2026 23:59:59"],
            ["", "Полевской", "Количество заказов всего (зал+самовывоз+доставка)", "", "890", "3 776", "771", "3 381"],
            ["", "Полевской", "Положительных оценок Ревии", "", "45", "399", "51", "398"],
            ["", "Полевской", "Негативных оценок и отзывов", "", "13", "81", "28", "63"],
            ["", "Полевской", "Негативных отзывов по качеству продукта", "", "5", "15", "4", "6"],
            ["", "Полевской", "Негативных отзывов по качеству сервиса", "", "8", "65", "23", "56"],
            ["Доставка", "Полевской", "Количество негативных оценок и отзывов", "", "12", "53", "19", "45"],
            ["Доставка", "Полевской", "Доля негативных оценок и отзывов от количества заказов на доставку", "", "8,70%", "8,19%", "14,73%", "7,35%"],
            ["Опоздания", "Полевской", "Количество заказов с опозданием на доставку", "", "4", "20", "4", "8"],
            ["Опоздания", "Полевской", "Доля заказов с опозданием от общего количества заказов на доставку", "", "2,90%", "3,09%", "3,10%", "1,31%"],
        ]

        with patch.object(provider, "_fetch_csv_rows", AsyncMock(return_value=rows)):
            result = await provider.build_report(point_name="Полевской, Ленина 11", period=ReviewAnalyticsPeriod(kind="week", label="за неделю"))

        self.assertEqual(result["status"], "ok")
        self.assertIn("📊 Italian Pizza", result["report_text"])
        self.assertIn("🧾 Заказов всего: 771", result["report_text"])
        self.assertIn("⚠️ Негативных оценок и отзывов: 28", result["report_text"])
        self.assertIn("⏱️ Опоздания доставки: 4 заказов", result["report_text"])

    async def test_build_report_uses_latest_monthly_column(self):
        provider = ItalianPizzaSheetAnalyticsProvider(["https://example.com/sheet"])
        rows = [
            ["", "", "Полевской", "", "05.01.2026", "01.01.2026", "02.02.2026", "01.02.2026"],
            ["", "", "", "", "11.01.2026", "31.01.2026 23:59:59", "08.02.2026", "28.02.2026 23:59:59"],
            ["", "Полевской", "Количество заказов всего (зал+самовывоз+доставка)", "", "890", "3 776", "771", "3 381"],
            ["", "Полевской", "Положительных оценок Ревии", "", "45", "399", "51", "398"],
            ["", "Полевской", "Негативных оценок и отзывов", "", "13", "81", "28", "63"],
        ]

        with patch.object(provider, "_fetch_csv_rows", AsyncMock(return_value=rows)):
            result = await provider.build_report(point_name="Полевской, Ленина 11", period=ReviewAnalyticsPeriod(kind="month", label="за месяц"))

        self.assertEqual(result["status"], "ok")
        self.assertIn("Период: за месяц", result["report_text"])
        self.assertIn("🧾 Заказов всего: 3 381", result["report_text"])
        self.assertIn("⚠️ Негативных оценок и отзывов: 63", result["report_text"])


class ReviewAnalyticsCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_report_combines_available_sources(self):
        with patch.object(
            review_analytics_coordinator._italian_pizza,
            "build_report",
            AsyncMock(return_value={"status": "ok", "source": "italian_pizza_sheet", "report_text": "📊 Italian Pizza\nsheet stats"}),
        ), patch.object(
            review_analytics_coordinator._rocketdata,
            "build_report",
            AsyncMock(return_value={"status": "ok", "source": "rocketdata", "report_text": "⭐ RocketData\nrocket stats"}),
        ):
            result = await review_analytics_coordinator.build_report(
                user_message="покажи отзывы по Полевской, Ленина 11 за неделю",
                point_name="Полевской, Ленина 11",
                user_id=17,
            )

        self.assertEqual(result["status"], "ok")
        self.assertIn("📣 Отчёт по отзывам за неделю", result["report_text"])
        self.assertIn("📊 Italian Pizza", result["report_text"])
        self.assertIn("⭐ RocketData", result["report_text"])

    async def test_build_report_returns_reasons_when_sources_unavailable(self):
        with patch.object(
            review_analytics_coordinator._italian_pizza,
            "build_report",
            AsyncMock(return_value={"status": "not_relevant", "source": "italian_pizza_sheet", "message": "Подходящий лист Italian Pizza для этой точки не найден."}),
        ), patch.object(
            review_analytics_coordinator._rocketdata,
            "build_report",
            AsyncMock(return_value={"status": "failed", "source": "rocketdata", "message": "Не удалось собрать отчёт из RocketData: timeout"}),
        ):
            result = await review_analytics_coordinator.build_report(
                user_message="покажи отзывы по Верхний Уфалей, Ленина 147 за неделю",
                point_name="Верхний Уфалей, Ленина 147",
                user_id=17,
            )

        self.assertEqual(result["status"], "not_configured")
        self.assertIn("Верхний Уфалей, Ленина 147", result["message"])
        self.assertIn("Italian Pizza", result["message"])
        self.assertIn("RocketData", result["message"])


class ReviewReportServiceAnalyticsTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_report_requests_point_for_weekly_analytics(self):
        service = ReviewReportService()
        result = await service.build_report("отзывы за неделю", point_name=None, user_id=17)
        self.assertEqual(result["status"], "needs_point")
        self.assertIn("укажите конкретную точку", result["message"])


if __name__ == "__main__":
    unittest.main()
