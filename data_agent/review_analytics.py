from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp
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


class ItalianPizzaSheetAnalyticsProvider:
    source_name = "italian_pizza_sheet"

    def __init__(self, sheet_urls: list[str]) -> None:
        self._sheet_urls = [item for item in sheet_urls if item]

    async def build_report(self, *, point_name: str, period: ReviewAnalyticsPeriod) -> dict[str, Any]:
        if not self._sheet_urls:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Источник статистики Italian Pizza не настроен.",
            }

        last_error: str | None = None
        for source_url in self._sheet_urls:
            csv_url = self._normalize_google_sheet_url(source_url)
            try:
                rows = await self._fetch_csv_rows(csv_url)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Italian Pizza reviews sheet fetch failed url=%s error=%s", csv_url, exc)
                continue

            if len(rows) < 3:
                continue

            sheet_point_name = self._extract_sheet_point_name(rows)
            if not self._matches_point(sheet_point_name, point_name):
                continue

            period_index = self._select_period_column(rows, period.kind)
            if period_index is None:
                return {
                    "status": "failed",
                    "source": self.source_name,
                    "message": f"В статистике Italian Pizza не найден столбец для периода {period.label}.",
                }

            report_text = self._render_report(rows, period_index=period_index, point_name=point_name, period=period)
            if not report_text:
                return {
                    "status": "failed",
                    "source": self.source_name,
                    "message": "Не удалось собрать статистику Italian Pizza из таблицы.",
                }

            return {
                "status": "ok",
                "source": self.source_name,
                "provider_label": "Italian Pizza",
                "report_text": report_text,
                "requested_point": point_name,
                "sheet_point_name": sheet_point_name,
                "period_kind": period.kind,
            }

        if last_error:
            return {
                "status": "failed",
                "source": self.source_name,
                "message": f"Не удалось загрузить статистику Italian Pizza: {last_error}",
            }

        return {
            "status": "not_relevant",
            "source": self.source_name,
            "message": "Подходящий лист Italian Pizza для этой точки не найден.",
        }

    def _normalize_google_sheet_url(self, source_url: str) -> str:
        if "/export?" in source_url and "format=csv" in source_url:
            return source_url

        parsed = urlparse(source_url)
        if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
            return source_url

        match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
        if not match:
            return source_url

        sheet_id = match.group(1)
        query = parse_qs(parsed.query)
        gid = query.get("gid", ["0"])[0]
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    async def _fetch_csv_rows(self, csv_url: str) -> list[list[str]]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(csv_url) as response:
                response.raise_for_status()
                content = await response.read()

        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        return [[self._clean_cell(cell) for cell in row] for row in reader]

    def _clean_cell(self, value: str) -> str:
        cleaned = (value or "").replace("\xa0", " ").replace("Â", "").strip()
        if "Ð" in cleaned or "Ñ" in cleaned:
            try:
                cleaned = cleaned.encode("latin1").decode("utf-8")
            except Exception:
                pass
        return cleaned.strip()

    def _extract_sheet_point_name(self, rows: list[list[str]]) -> str:
        candidates = []
        for row_index, column_index in ((0, 2), (2, 1), (0, 1), (1, 1)):
            if row_index < len(rows) and column_index < len(rows[row_index]):
                value = rows[row_index][column_index].strip()
                if value:
                    candidates.append(value)
        return candidates[0] if candidates else ""

    def _normalize_label(self, value: str) -> str:
        normalized = (value or "").lower().replace("ё", "е")
        normalized = normalized.replace("ул.", " ").replace("улица", " ").replace("д.", " ")
        normalized = normalized.replace("тц", " ")
        normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

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

    def _matches_point(self, sheet_point_name: str, requested_point: str) -> bool:
        sheet_label = self._normalize_label(sheet_point_name)
        aliases = self._point_aliases(requested_point)
        return any(alias in sheet_label or sheet_label in alias for alias in aliases)

    def _try_parse_date(self, value: str) -> Optional[datetime]:
        cleaned = self._clean_cell(value)
        if not cleaned:
            return None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        return None

    def _select_period_column(self, rows: list[list[str]], period_kind: str) -> Optional[int]:
        if len(rows) < 3:
            return None
        start_row = rows[0]
        end_row = rows[1]
        reference_row = rows[2]
        candidates: list[int] = []
        for index in range(max(len(start_row), len(end_row))):
            start_at = self._try_parse_date(start_row[index] if index < len(start_row) else "")
            end_at = self._try_parse_date(end_row[index] if index < len(end_row) else "")
            if not start_at or not end_at:
                continue
            span_days = max((end_at - start_at).days, 0)
            column_kind = "month" if span_days >= 20 else "week"
            if column_kind != period_kind:
                continue
            if index < len(reference_row) and self._clean_cell(reference_row[index]):
                candidates.append(index)
        return candidates[-1] if candidates else None

    def _rows_by_key(self, rows: list[list[str]], period_index: int) -> dict[tuple[str, str], str]:
        values: dict[tuple[str, str], str] = {}
        for row in rows[2:]:
            if len(row) <= period_index:
                continue
            section = self._normalize_label(row[0] if len(row) > 0 else "")
            metric = self._normalize_label(row[2] if len(row) > 2 else "")
            value = self._clean_cell(row[period_index])
            if not metric or not value:
                continue
            values[(section, metric)] = value
        return values

    def _find_value(self, values: dict[tuple[str, str], str], *, section: str | None, metric_markers: list[str]) -> str | None:
        normalized_section = self._normalize_label(section or "")
        for (row_section, row_metric), value in values.items():
            if normalized_section and row_section != normalized_section:
                continue
            if all(marker in row_metric for marker in metric_markers):
                return value
        return None

    def _render_report(self, rows: list[list[str]], *, period_index: int, point_name: str, period: ReviewAnalyticsPeriod) -> str:
        values = self._rows_by_key(rows, period_index)
        start_at = self._try_parse_date(rows[0][period_index] if period_index < len(rows[0]) else "")
        end_at = self._try_parse_date(rows[1][period_index] if period_index < len(rows[1]) else "")
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
        delay_share = self._find_value(values, section="опоздания", metric_markers=["доля", "опозданием", "доставку"])
        delay_count = self._find_value(values, section="опоздания", metric_markers=["количество", "опозданием", "доставку"])
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
            lines.append(
                "🍕 Продукт / 🤝 сервис: "
                f"{negative_product or '0'} / {negative_service or '0'}"
            )
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
        if len(lines) <= 3:
            return ""
        return "\n".join(lines)


class RocketDataReviewsProvider:
    source_name = "rocketdata"

    async def build_report(self, *, point_name: str, period: ReviewAnalyticsPeriod, user_message: str, user_id: int | None) -> dict[str, Any]:
        if not user_id:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Не удалось определить пользователя для RocketData.",
            }

        system = self._find_connected_system(user_id)
        if not system:
            return {
                "status": "not_configured",
                "source": self.source_name,
                "message": "Система RocketData не подключена.",
            }

        task_text = (
            "Авторизуйся в RocketData и собери отчёт по отзывам для одной точки.\n\n"
            f"Точка: {point_name}\n"
            f"Период: {period.label}\n"
            "Нужно:\n"
            "1. Найти именно эту точку\n"
            "2. Собрать сводку по категориям: сервис, доставка, кухня, общий отчёт\n"
            "3. Сфокусироваться на негативе, повторяющихся жалобах и рисках\n"
            "4. Отдельно отметить сильные стороны, если они явно видны\n"
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
                "status": "failed",
                "source": self.source_name,
                "message": f"Не удалось собрать отчёт из RocketData: {exc}",
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

            skipped = [item for item in provider_results if item.get("status") in {"not_configured", "not_relevant"}]
            if skipped:
                skipped_labels = []
                for item in skipped:
                    source = item.get("source")
                    skipped_labels.append("RocketData" if source == "rocketdata" else "Italian Pizza")
                lines.append("")
                lines.append(f"ℹ️ Недоступные источники: {', '.join(dict.fromkeys(skipped_labels))}")

            return {
                "status": "ok",
                "source": "reviews_multi_source",
                "providers_used": [item.get("source") for item in ok_results],
                "providers_skipped": [item.get("source") for item in provider_results if item.get("status") != "ok"],
                "period_kind": period.kind,
                "window_label": period.label,
                "report_text": "\n".join(lines).strip(),
            }

        failed_results = [item for item in provider_results if item.get("status") == "failed"]
        if failed_results:
            message = self._build_unavailable_message(provider_results, point_name=point_name, period=period)
            return {
                "status": "not_configured",
                "source": "reviews_multi_source",
                "message": message,
            }

        return {
            "status": "not_configured",
            "source": "reviews_multi_source",
            "message": self._build_unavailable_message(provider_results, point_name=point_name, period=period),
        }

    def _build_unavailable_message(
        self,
        provider_results: list[dict[str, Any]],
        *,
        point_name: str,
        period: ReviewAnalyticsPeriod,
    ) -> str:
        reasons: list[str] = []
        for item in provider_results:
            source = item.get("source")
            source_label = "RocketData" if source == "rocketdata" else "Italian Pizza"
            message = (item.get("message") or "").strip()
            if message:
                reasons.append(f"{source_label}: {message}")

        if not reasons:
            reasons.append("Для этой точки ещё не подключён источник weekly/monthly аналитики.")

        return (
            f"Для точки {point_name} пока не удалось собрать отчёт по отзывам {period.label}.\n"
            f"Причины: {'; '.join(reasons)}"
        )


review_analytics_coordinator = ReviewAnalyticsCoordinator()
