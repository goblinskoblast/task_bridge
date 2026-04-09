from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
from dateutil import parser as date_parser

from config import REVIEWS_SHEET_URL
from .italian_pizza import resolve_italian_pizza_point
from .review_analytics import review_analytics_coordinator


KEYWORD_CATEGORIES = {
    "service": ["сервис", "обслуж", "официант", "кассир", "персонал", "хам", "вежл", "долго отвеч", "груб"],
    "delivery": ["достав", "курьер", "привез", "опозд", "задерж", "долго ех", "не доех", "холодн"],
    "kitchen": ["кухн", "пицц", "еда", "блюд", "вкус", "пересол", "сырая", "горел", "ингредиент"],
}

POSITIVE_MARKERS = ["спасибо", "отлич", "вкусн", "быстро", "понрав", "супер", "класс", "хорош", "рекомен"]
NEGATIVE_MARKERS = ["плохо", "ужас", "долго", "невкус", "хам", "ошиб", "не привез", "проблем", "холодн", "гряз"]


@dataclass
class ReviewWindow:
    start: datetime
    end: datetime
    label: str


class ReviewReportService:
    def supports_analytics_request(self, user_message: str) -> bool:
        return review_analytics_coordinator.supports_request(user_message)

    async def build_report(self, user_message: str, point_name: str | None = None, user_id: int | None = None) -> dict[str, Any]:
        if self.supports_analytics_request(user_message):
            if not point_name:
                return {
                    "status": "needs_point",
                    "source": "reviews_multi_source",
                    "message": "Для недельного или месячного отчёта по отзывам укажите конкретную точку.",
                }
            return await review_analytics_coordinator.build_report(user_message=user_message, point_name=point_name, user_id=user_id)
        return await self._build_legacy_report(user_message, point_name=point_name)

    async def _build_legacy_report(self, user_message: str, point_name: str | None = None) -> dict[str, Any]:
        if not REVIEWS_SHEET_URL:
            return {
                "status": "not_configured",
                "source": "google_sheets_csv",
                "message": "Не задан REVIEWS_SHEET_URL",
            }

        csv_url = self._normalize_google_sheet_url(REVIEWS_SHEET_URL)
        rows = await self._fetch_csv_rows(csv_url)
        window = self._resolve_window(user_message)
        filtered_rows = self._filter_rows(rows, window)
        matched_branches: list[str] = []
        if point_name:
            filtered_rows, matched_branches = self._filter_rows_by_point(filtered_rows, point_name)
        return self._build_summary(filtered_rows, window, csv_url, point_name=point_name, matched_branches=matched_branches)

    async def build_report_for_window_label(self, window_label: str) -> dict[str, Any]:
        synthetic_request = f"отзывы {window_label}".strip()
        return await self._build_legacy_report(synthetic_request)

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

    async def _fetch_csv_rows(self, csv_url: str) -> list[dict[str, str]]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(csv_url) as response:
                response.raise_for_status()
                content = await response.text(encoding="utf-8-sig")

        reader = csv.DictReader(io.StringIO(content))
        return [dict(row) for row in reader if any((value or "").strip() for value in row.values())]

    def _resolve_window(self, user_message: str) -> ReviewWindow:
        now = datetime.now()
        lowered = re.sub(r"\s+", " ", user_message.lower()).strip()

        if "вчера" in lowered:
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return ReviewWindow(start=start, end=end, label="за вчера")

        if "сегодня" in lowered:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return ReviewWindow(start=start, end=end, label="за сегодня")

        if "12 часов" in lowered or "последние 12" in lowered or "предыдущие 12" in lowered:
            return self._relative_hours_window(now, hours=12)

        if "3 часа" in lowered or "последние 3" in lowered or "предыдущие 3" in lowered:
            return self._relative_hours_window(now, hours=3)

        if self._is_last_day_request(lowered):
            return self._relative_hours_window(now, hours=24)

        if self._is_last_week_request(lowered):
            start = now - timedelta(days=7)
            return ReviewWindow(start=start, end=now, label="за последнюю неделю")

        if "month" in lowered or "месяц" in lowered:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return ReviewWindow(start=start, end=end, label="за текущий месяц")

        if self._is_current_week_request(lowered):
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            return ReviewWindow(start=start, end=end, label="за текущую неделю")

        explicit = self._parse_explicit_range(lowered, now)
        if explicit:
            return explicit

        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return ReviewWindow(start=start, end=end, label="за текущую неделю")

    def _is_last_day_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in [
                "сутки",
                "24 часа",
                "последние 24",
                "за день",
                "за последний день",
                "последний день",
            ]
        )

    def _is_last_week_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in [
                "за неделю",
                "за последнюю неделю",
                "последняя неделя",
                "7 дней",
                "последние 7 дней",
                "за 7 дней",
                "еженедель",
            ]
        )

    def _is_current_week_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in [
                "текущая неделя",
                "эта неделя",
                "current week",
                "this week",
            ]
        )

    def _relative_hours_window(self, now: datetime, *, hours: int) -> ReviewWindow:
        start = now - timedelta(hours=hours)
        return ReviewWindow(start=start, end=now, label=f"за последние {hours} часов")

    def _parse_explicit_range(self, text: str, now: datetime) -> ReviewWindow | None:
        matches = re.findall(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text)
        if len(matches) < 2:
            return None

        try:
            start = self._parse_partial_date(matches[0], now).replace(hour=0, minute=0, second=0, microsecond=0)
            end = self._parse_partial_date(matches[1], now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        except Exception:
            return None

        if end <= start:
            end = end.replace(year=end.year + 1)

        return ReviewWindow(start=start, end=end, label=f"с {matches[0]} по {matches[1]}")

    def _parse_partial_date(self, value: str, now: datetime) -> datetime:
        if re.search(r"\d{4}", value):
            return date_parser.parse(value, dayfirst=True)
        parsed = date_parser.parse(f"{value}.{now.year}", dayfirst=True)
        if parsed < now - timedelta(days=180):
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed

    def _filter_rows(self, rows: list[dict[str, str]], window: ReviewWindow) -> list[dict[str, str]]:
        filtered: list[dict[str, str]] = []
        for row in rows:
            created_at = self._extract_row_datetime(row)
            if not created_at:
                continue
            if window.start <= created_at < window.end:
                filtered.append(dict(row))
        return filtered

    def _normalize_label(self, value: str) -> str:
        normalized = (value or "").lower().replace("ё", "е")
        normalized = normalized.replace("ул.", " ").replace("улица", " ").replace("д.", " ")
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

    def _filter_rows_by_point(self, rows: list[dict[str, str]], point_name: str) -> tuple[list[dict[str, str]], list[str]]:
        aliases = self._point_aliases(point_name)
        filtered: list[dict[str, str]] = []
        matched_branches: list[str] = []
        for row in rows:
            branch = self._extract_branch(row) or ""
            normalized_branch = self._normalize_label(branch)
            if not normalized_branch:
                continue
            if any(alias in normalized_branch or normalized_branch in alias for alias in aliases):
                filtered.append(dict(row))
                clean_branch = branch.strip()
                if clean_branch and clean_branch not in matched_branches:
                    matched_branches.append(clean_branch)
        return filtered, matched_branches

    def _extract_row_datetime(self, row: dict[str, str]) -> datetime | None:
        for key, value in row.items():
            if not value:
                continue
            lowered = key.lower()
            if any(token in lowered for token in ["date", "дат", "created", "time", "время"]):
                try:
                    return date_parser.parse(value, dayfirst=True)
                except Exception:
                    continue
        return None

    def _build_summary(
        self,
        rows: list[dict[str, str]],
        window: ReviewWindow,
        source_url: str,
        *,
        point_name: str | None = None,
        matched_branches: list[str] | None = None,
    ) -> dict[str, Any]:
        category_counts: Counter[str] = Counter()
        sentiment_counts: Counter[str] = Counter()
        issue_counts: Counter[str] = Counter()
        branch_counts: Counter[str] = Counter()
        by_rating: Counter[str] = Counter()
        critical_category_counts: Counter[str] = Counter()
        critical_issue_counts: Counter[str] = Counter()
        critical_rows_count = 0

        for row in rows:
            text = self._extract_text(row)
            branch = self._extract_branch(row)
            rating = self._extract_rating(row)
            category = self._classify_category(text)
            sentiment = self._classify_sentiment(text, rating)
            is_critical = self._is_critical_review(text, rating, sentiment)

            category_counts[category] += 1
            sentiment_counts[sentiment] += 1
            if branch:
                branch_counts[branch] += 1
            if rating is not None:
                by_rating[str(rating)] += 1

            if is_critical:
                critical_rows_count += 1
                critical_category_counts[category] += 1
                for phrase in self._extract_reasons(text, positive=False):
                    critical_issue_counts[phrase] += 1
            elif sentiment != "positive":
                for phrase in self._extract_reasons(text, positive=False):
                    issue_counts[phrase] += 1

        return {
            "status": "ok",
            "source": "google_sheets_csv",
            "window_label": window.label,
            "source_url": source_url,
            "reviews_count": len(rows),
            "critical_reviews_count": critical_rows_count,
            "category_counts": dict(category_counts),
            "critical_category_counts": dict(critical_category_counts),
            "sentiment_counts": dict(sentiment_counts),
            "top_issues": critical_issue_counts.most_common(5) or issue_counts.most_common(5),
            "top_branches": branch_counts.most_common(5),
            "matched_branches": matched_branches or [],
            "requested_point": point_name,
            "ratings": dict(by_rating),
            "report_text": self._render_report(
                rows_count=len(rows),
                critical_rows_count=critical_rows_count,
                window_label=window.label,
                point_name=point_name,
                matched_branches=matched_branches or [],
                category_counts=category_counts,
                critical_category_counts=critical_category_counts,
                sentiment_counts=sentiment_counts,
                issue_counts=critical_issue_counts or issue_counts,
                branch_counts=branch_counts,
            ),
        }

    def _extract_text(self, row: dict[str, str]) -> str:
        parts: list[str] = []
        for key, value in row.items():
            if not value:
                continue
            lowered = key.lower()
            if any(token in lowered for token in ["comment", "review", "text", "отзыв", "коммент", "описан", "message"]):
                parts.append(value.strip())
        if not parts:
            parts = [value.strip() for value in row.values() if value and len(value.strip()) > 10]
        return " ".join(parts)

    def _extract_branch(self, row: dict[str, str]) -> str | None:
        for key, value in row.items():
            if not value:
                continue
            lowered = key.lower()
            if any(token in lowered for token in ["branch", "location", "store", "point", "точк", "филиал", "ресторан"]):
                return value.strip()
        return None

    def _extract_rating(self, row: dict[str, str]) -> int | None:
        for key, value in row.items():
            if not value:
                continue
            lowered = key.lower()
            if any(token in lowered for token in ["rating", "rate", "stars", "оцен", "звезд"]):
                match = re.search(r"\d+", value)
                if match:
                    try:
                        return int(match.group(0))
                    except ValueError:
                        return None
        return None

    def _classify_category(self, text: str) -> str:
        lowered = text.lower()
        scores: dict[str, int] = defaultdict(int)
        for category, markers in KEYWORD_CATEGORIES.items():
            for marker in markers:
                if marker in lowered:
                    scores[category] += 1
        if not scores:
            return "other"
        return max(scores.items(), key=lambda item: item[1])[0]

    def _classify_sentiment(self, text: str, rating: int | None) -> str:
        lowered = text.lower()
        positive = sum(1 for marker in POSITIVE_MARKERS if marker in lowered)
        negative = sum(1 for marker in NEGATIVE_MARKERS if marker in lowered)

        if rating is not None:
            if rating >= 4:
                positive += 2
            elif rating <= 2:
                negative += 2

        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"

    def _extract_reasons(self, text: str, positive: bool) -> list[str]:
        lowered = re.sub(r"\s+", " ", text.lower()).strip()
        phrases: list[str] = []
        markers = POSITIVE_MARKERS if positive else NEGATIVE_MARKERS
        for marker in markers:
            if marker in lowered:
                phrases.append(marker)
        return phrases[:3]

    def _is_critical_review(self, text: str, rating: int | None, sentiment: str) -> bool:
        if rating is not None and rating < 4:
            return True
        if sentiment == "negative":
            lowered = text.lower()
            if any(marker in lowered for marker in NEGATIVE_MARKERS):
                return True
        return False

    def _render_report(
        self,
        rows_count: int,
        critical_rows_count: int,
        window_label: str,
        point_name: str | None,
        matched_branches: list[str],
        category_counts: Counter[str],
        critical_category_counts: Counter[str],
        sentiment_counts: Counter[str],
        issue_counts: Counter[str],
        branch_counts: Counter[str],
    ) -> str:
        lines = [f"Отчёт по отзывам {window_label}", f"Всего отзывов: {rows_count}"]
        if point_name:
            lines.insert(1, f"Точка: {point_name}")
        if rows_count == 0:
            if point_name:
                lines.append("По выбранной точке за этот период отзывов не найдено.")
            else:
                lines.append("За выбранный период отзывов не найдено.")
            return "\n".join(lines)

        lines.append(f"Критических отзывов (<4 звезды): {critical_rows_count}")

        if matched_branches:
            lines.append(f"Совпавшие точки в источнике: {', '.join(matched_branches[:3])}")
        if branch_counts:
            top_branches = ", ".join(f"{name} ({count})" for name, count in branch_counts.most_common(3))
            lines.append(f"Точки с наибольшим числом отзывов: {top_branches}")

        if critical_rows_count:
            lines.append(
                "Где чаще всего проблемы: "
                f"сервис {critical_category_counts.get('service', 0)}, "
                f"доставка {critical_category_counts.get('delivery', 0)}, "
                f"кухня {critical_category_counts.get('kitchen', 0)}, "
                f"прочее {critical_category_counts.get('other', 0)}"
            )
        else:
            lines.append("Критических отзывов с оценкой ниже 4 звёзд за этот период не найдено.")
            lines.append(
                "Общая тональность: "
                f"позитивных {sentiment_counts.get('positive', 0)}, "
                f"нейтральных {sentiment_counts.get('neutral', 0)}, "
                f"негативных {sentiment_counts.get('negative', 0)}"
            )
            lines.append(
                "Категории: "
                f"сервис {category_counts.get('service', 0)}, "
                f"доставка {category_counts.get('delivery', 0)}, "
                f"кухня {category_counts.get('kitchen', 0)}, "
                f"прочее {category_counts.get('other', 0)}"
            )

        if issue_counts:
            top_issues = ", ".join(f"{phrase} ({count})" for phrase, count in issue_counts.most_common(5))
            lines.append(f"Основные проблемы: {top_issues}")

        return "\n".join(lines)


review_report_service = ReviewReportService()
