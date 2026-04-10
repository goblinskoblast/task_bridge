from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
import openpyxl
from sqlalchemy import or_

from config import ITALIAN_PIZZA_REVIEWS_SHEET_URLS
from db.database import get_db_session
from db.models import DataAgentSystem, User

from .browser_agent import browser_agent
from .italian_pizza import resolve_italian_pizza_point

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewAnalyticsPeriod:
    kind: str
    label: str


@dataclass(frozen=True)
class WorkbookSheet:
    title: str
    rows: list[list[Any]]


class ItalianPizzaSheetAnalyticsProvider:
    source_name = "italian_pizza_sheet"

    def __init__(self, sheet_urls: list[str]) -> None:
        self._sheet_urls = [item for item in sheet_urls if item]

    async def build_report(self, *, point_name: str, period: ReviewAnalyticsPeriod) -> dict[str, Any]:
        if not self._sheet_urls:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Отчёт по отзывам для этой точки пока недоступен.",
            }

        last_error: str | None = None
        for source_url in self._sheet_urls:
            xlsx_url = self._normalize_google_sheet_xlsx_url(source_url)
            try:
                sheets = await self._fetch_workbook_sheets(xlsx_url)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Italian Pizza workbook fetch failed url=%s error=%s", xlsx_url, exc)
                continue

            report = self._build_workbook_report(sheets, point_name=point_name, period=period)
            if report:
                return {
                    "status": "ok",
                    "source": self.source_name,
                    "provider_label": "Italian Pizza",
                    "report_text": report,
                    "requested_point": point_name,
                    "period_kind": period.kind,
                }

        if last_error:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Отчёт по отзывам для этой точки пока недоступен.",
            }

        return {
            "status": "not_relevant",
            "source": self.source_name,
            "message": "Отчёт по отзывам для этой точки пока недоступен.",
        }

    def _normalize_google_sheet_xlsx_url(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
            return source_url

        match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
        if not match:
            return source_url

        sheet_id = match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"

    async def _fetch_workbook_sheets(self, xlsx_url: str) -> list[WorkbookSheet]:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(xlsx_url) as response:
                response.raise_for_status()
                content = await response.read()

        workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        snapshots: list[WorkbookSheet] = []
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            snapshots.append(WorkbookSheet(title=str(sheet.title or "").strip(), rows=rows))
        return snapshots

    def _build_workbook_report(
        self,
        sheets: list[WorkbookSheet],
        *,
        point_name: str,
        period: ReviewAnalyticsPeriod,
    ) -> str | None:
        analytics_sheets = [sheet for sheet in sheets if "аналит" in self._normalize_label(sheet.title)]
        if not analytics_sheets:
            analytics_sheets = sheets

        for sheet in analytics_sheets:
            report = self._build_sheet_report(sheet.rows, point_name=point_name, period=period)
            if report:
                return report
        return None

    def _build_sheet_report(
        self,
        rows: list[list[Any]],
        *,
        point_name: str,
        period: ReviewAnalyticsPeriod,
    ) -> str | None:
        if len(rows) < 3:
            return None

        period_index = self._select_period_column(rows, period.kind)
        if period_index is None:
            return None

        values_by_point = self._rows_by_point(rows, period_index)
        matched_point = self._match_point_key(values_by_point.keys(), point_name)
        if not matched_point:
            return None

        values = values_by_point[matched_point]
        start_at = self._try_parse_date(rows[0][period_index] if period_index < len(rows[0]) else None)
        end_at = self._try_parse_date(rows[1][period_index] if period_index < len(rows[1]) else None)
        period_label = period.label
        if start_at and end_at:
            period_label = f"{period.label} ({start_at:%d.%m.%Y} - {end_at:%d.%m.%Y})"

        total_orders = self._find_value(values, section=None, metric_markers=["количество", "заказов", "всего"])
        positive_revii = self._find_value(values, section=None, metric_markers=["положительных", "оценок", "ревии"])
        external_positive = self._find_value(values, section=None, metric_markers=["положительных", "других", "источников"])
        negative_total = self._find_value(values, section=None, metric_markers=["негативных", "оценок", "отзывов"])
        negative_product = self._find_value(values, section=None, metric_markers=["негативных", "качеству", "продукта"])
        negative_service = self._find_value(values, section=None, metric_markers=["негативных", "качеству", "сервиса"])
        delivery_negative = self._find_value(values, section="доставка", metric_markers=["количество", "негативных"])
        delivery_share = self._find_value(values, section="доставка", metric_markers=["доля", "негативных", "доставку"])
        pickup_negative = self._find_value(values, section="самовывоз", metric_markers=["количество", "негативных"])
        pickup_share = self._find_value(values, section="самовывоз", metric_markers=["доля", "негативных", "самовывоз"])
        hall_negative = self._find_value(values, section="зал", metric_markers=["количество", "негативных"])
        hall_share = self._find_value(values, section="зал", metric_markers=["доля", "негативных", "зале"])
        delay_count = self._find_value(values, section="опоздания", metric_markers=["количество", "опозданием", "доставку"])
        delay_share = self._find_value(values, section="опоздания", metric_markers=["доля", "опозданием", "доставку"])
        lateness_bonus = self._find_value(values, section=None, metric_markers=["бонусов", "опоздание"])

        lines = [
            "📊 Italian Pizza",
            f"Точка: {point_name}",
            f"Период: {period_label}",
        ]
        if total_orders:
            lines.append(f"🧾 Заказов всего: {total_orders}")
        if positive_revii or external_positive:
            positive_line = positive_revii or "0"
            if external_positive:
                positive_line = f"{positive_line} (+ {external_positive} из других источников)"
            lines.append(f"🙂 Положительных оценок: {positive_line}")
        if negative_total:
            lines.append(f"⚠️ Негативных оценок и отзывов: {negative_total}")
        if negative_product or negative_service:
            lines.append(f"🍕 Продукт / 🤝 сервис: {negative_product or '0'} / {negative_service or '0'}")
        if delivery_negative or delivery_share:
            lines.append(f"🛵 Доставка: {delivery_negative or '0'} негативных ({delivery_share or 'н/д'})")
        if pickup_negative or pickup_share:
            lines.append(f"🥡 Самовывоз: {pickup_negative or '0'} негативных ({pickup_share or 'н/д'})")
        if hall_negative or hall_share:
            lines.append(f"🏠 Зал: {hall_negative or '0'} негативных ({hall_share or 'н/д'})")
        if delay_count or delay_share:
            lines.append(f"⏱️ Опоздания доставки: {delay_count or '0'} заказов ({delay_share or 'н/д'})")
        if lateness_bonus:
            lines.append(f"🎁 Бонусов за опоздание: {lateness_bonus}")

        return "\n".join(lines) if len(lines) > 3 else None

    def _rows_by_point(self, rows: list[list[Any]], period_index: int) -> dict[str, dict[tuple[str, str], str]]:
        values_by_point: dict[str, dict[tuple[str, str], str]] = {}
        for row in rows[2:]:
            if len(row) <= period_index:
                continue
            point_raw = self._clean_cell(row[1] if len(row) > 1 else "")
            metric = self._normalize_label(self._clean_cell(row[2] if len(row) > 2 else ""))
            if not point_raw or not metric:
                continue
            point_key = self._normalize_label(point_raw)
            section = self._normalize_label(self._clean_cell(row[0] if len(row) > 0 else ""))
            value = self._clean_cell(row[period_index])
            if not value:
                continue
            values_by_point.setdefault(point_key, {})[(section, metric)] = value
        return values_by_point

    def _match_point_key(self, available_points: Any, requested_point: str) -> str | None:
        aliases = self._point_aliases(requested_point)
        for candidate in available_points:
            normalized_candidate = self._normalize_label(str(candidate))
            if any(alias in normalized_candidate or normalized_candidate in alias for alias in aliases):
                return candidate
        return None

    def _point_aliases(self, point_name: str) -> list[str]:
        aliases: list[str] = []
        variants = [point_name]
        resolved_point = resolve_italian_pizza_point(point_name)
        if resolved_point:
            variants.extend(
                [
                    resolved_point.display_name,
                    resolved_point.address,
                    resolved_point.city,
                    f"{resolved_point.city} {resolved_point.address}",
                ]
            )

        for raw in variants:
            normalized = self._normalize_label(raw)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        return aliases

    def _select_period_column(self, rows: list[list[Any]], period_kind: str) -> Optional[int]:
        start_row = rows[0]
        end_row = rows[1]
        candidates: list[int] = []
        for index in range(max(len(start_row), len(end_row))):
            start_at = self._try_parse_date(start_row[index] if index < len(start_row) else None)
            end_at = self._try_parse_date(end_row[index] if index < len(end_row) else None)
            if not start_at or not end_at:
                continue
            span_days = max((end_at - start_at).days, 0)
            column_kind = "month" if span_days >= 20 else "week"
            if column_kind != period_kind:
                continue
            candidates.append(index)
        return candidates[-1] if candidates else None

    def _find_value(
        self,
        values: dict[tuple[str, str], str],
        *,
        section: str | None,
        metric_markers: list[str],
    ) -> str | None:
        normalized_section = self._normalize_label(section or "")
        for (row_section, row_metric), value in values.items():
            if normalized_section and row_section != normalized_section:
                continue
            if all(marker in row_metric for marker in metric_markers):
                return value
        return None

    def _clean_cell(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            if value.time() != datetime.min.time():
                return value.strftime("%d.%m.%Y %H:%M:%S")
            return value.strftime("%d.%m.%Y")
        return str(value).replace("\xa0", " ").strip()

    def _normalize_label(self, value: str) -> str:
        normalized = (value or "").lower().replace("ё", "е")
        normalized = normalized.replace("ул.", " ").replace("улица", " ").replace("д.", " ").replace("тц", " ")
        normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _try_parse_date(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        cleaned = self._clean_cell(value)
        if not cleaned:
            return None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        return None


class RocketDataReviewsProvider:
    source_name = "rocketdata"

    async def build_report(
        self,
        *,
        point_name: str,
        period: ReviewAnalyticsPeriod,
        user_message: str,
        user_id: int | None,
    ) -> dict[str, Any]:
        if not user_id:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Отчёт по отзывам для этой точки пока недоступен.",
            }

        system = self._find_connected_system(user_id)
        if not system:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Отчёт по отзывам для этой точки пока недоступен.",
            }

        task_text = (
            "Авторизуйся в RocketData и собери недельный или месячный отчёт по отзывам для одной точки.\n\n"
            f"Точка: {point_name}\n"
            f"Период: {period.label}\n"
            "Нужно:\n"
            "1. Найти именно эту точку\n"
            "2. Собрать сводку по категориям: сервис, доставка, кухня, общий отчёт\n"
            "3. Выделить повторяющиеся жалобы и зоны риска\n"
            "4. Коротко отметить сильные стороны, если они явно видны\n"
            "5. Вернуть компактный отчёт на русском языке\n\n"
            f"Исходный запрос пользователя: {user_message}"
        )
        try:
            data = await browser_agent.extract_data(
                url=system.url,
                username=system.login,
                encrypted_password=system.encrypted_password,
                user_task=task_text,
                progress_callback=None,
            )
        except Exception as exc:
            logger.warning("RocketData reviews fetch failed point=%s error=%s", point_name, exc)
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Отчёт по отзывам для этой точки пока недоступен.",
            }

        return {
            "status": "ok",
            "source": self.source_name,
            "provider_label": "RocketData",
            "report_text": f"⭐ RocketData\n{str(data).strip()}",
            "requested_point": point_name,
            "period_kind": period.kind,
        }

    def _find_connected_system(self, telegram_user_id: int) -> DataAgentSystem | None:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == telegram_user_id).first()
            if not user:
                return None
            return (
                db.query(DataAgentSystem)
                .filter(
                    DataAgentSystem.user_id == user.id,
                    DataAgentSystem.is_active == True,
                    or_(
                        DataAgentSystem.system_name == "rocketdata",
                        DataAgentSystem.url.contains("rocketdata"),
                    ),
                )
                .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
                .first()
            )
        finally:
            db.close()


class ReviewAnalyticsCoordinator:
    def __init__(self) -> None:
        self._italian_pizza = ItalianPizzaSheetAnalyticsProvider(ITALIAN_PIZZA_REVIEWS_SHEET_URLS)
        self._rocketdata = RocketDataReviewsProvider()

    def supports_request(self, user_message: str) -> bool:
        lowered = re.sub(r"\s+", " ", (user_message or "").lower()).strip()
        return any(marker in lowered for marker in ["недел", "7 дней", "месяц", "month"])

    def resolve_period(self, user_message: str) -> ReviewAnalyticsPeriod:
        lowered = re.sub(r"\s+", " ", (user_message or "").lower()).strip()
        if "месяц" in lowered or "month" in lowered:
            return ReviewAnalyticsPeriod(kind="month", label="за месяц")
        return ReviewAnalyticsPeriod(kind="week", label="за неделю")

    async def build_report(self, *, user_message: str, point_name: str, user_id: int | None) -> dict[str, Any]:
        period = self.resolve_period(user_message)
        provider_results = [
            await self._italian_pizza.build_report(point_name=point_name, period=period),
            await self._rocketdata.build_report(point_name=point_name, period=period, user_message=user_message, user_id=user_id),
        ]

        ok_results = [item for item in provider_results if item.get("status") == "ok"]
        if ok_results:
            lines = [
                f"📣 Отчёт по отзывам {period.label}",
                f"Точка: {point_name}",
            ]
            for result in ok_results:
                lines.append("")
                lines.append(result["report_text"].strip())
            return {
                "status": "ok",
                "source": "reviews_multi_source",
                "providers_used": [item.get("source") for item in ok_results],
                "providers_skipped": [item.get("source") for item in provider_results if item.get("status") != "ok"],
                "period_kind": period.kind,
                "window_label": period.label,
                "report_text": "\n".join(lines).strip(),
            }

        return {
            "status": "not_configured",
            "source": "reviews_multi_source",
            "message": f"Отчёт по отзывам для точки {point_name} {period.label} пока недоступен.",
        }


review_analytics_coordinator = ReviewAnalyticsCoordinator()
