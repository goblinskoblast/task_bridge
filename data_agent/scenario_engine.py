from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote

from db.database import get_db_session
from db.models import DataAgentSystem, SavedPoint, User

from .blanks_tool import blanks_tool
from .browser_agent import browser_agent
from .italian_pizza import ITALIAN_PIZZA_PORTAL_URL
from .models import ConnectedSystem
from .orchestrator import orchestrator
from .point_statistics import point_statistics_service
from .review_report import review_report_service
from .saved_points import saved_point_service
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)
DIRECT_ANSWER_SCENARIOS = {"reviews_report", "stoplist_report", "blanks_report"}


@dataclass
class ScenarioExecution:
    selected_tools: List[str]
    tool_results: Dict[str, dict]
    answer: Optional[str] = None


class BaseScenario:
    name = "general"
    selected_tools = ["orchestrator"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        return ScenarioExecution(
            selected_tools=list(self.selected_tools),
            tool_results={"orchestrator": {"status": "no_tool_selected", "message": "Для ответа не потребовались внутренние инструменты."}},
        )


class ReviewsReportScenario(BaseScenario):
    name = "reviews_report"
    selected_tools = ["review_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        point_name = slots.get("point_name")
        if point_name and _should_use_public_reviews_browser(user_message):
            tool_result = await _run_public_reviews_browser(user_message, targets=[point_name])
        else:
            tool_result = await review_report_service.build_report(user_message, point_name=point_name, user_id=user_id)
            if tool_result.get("status") in {"not_configured", "not_relevant"} and point_name:
                fallback_result = await _run_public_reviews_browser(
                    user_message,
                    targets=[point_name],
                    providers=["yandex_maps"],
                )
                if fallback_result.get("status") == "ok":
                    tool_result = fallback_result
            if tool_result.get("status") == "not_configured" and not point_name:
                tool_result = {
                    "status": "needs_point",
                    "message": "Чтобы собрать отзывы, укажите конкретную точку.",
                }
        return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"review_tool": tool_result})


class StoplistReportScenario(BaseScenario):
    name = "stoplist_report"
    selected_tools = ["stoplist_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        if slots.get("all_points"):
            tool_result = await _run_saved_points_stoplist_report(user_id=user_id)
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"stoplist_tool": tool_result})

        point_name = slots.get("point_name")
        logger.info("Stoplist scenario execute user_id=%s point=%s", user_id, point_name)
        if not point_name:
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"stoplist_tool": {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}})
        tool_result = await stoplist_tool.collect_for_point(url="", username="", encrypted_password="", point_name=point_name)
        tool_result = point_statistics_service.enrich_stoplist_report(user_id, point_name, tool_result)
        return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"stoplist_tool": tool_result})


class BlanksReportScenario(BaseScenario):
    name = "blanks_report"
    selected_tools = ["blanks_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        period_hint = slots.get("period_hint") or "за последние 3 часа"
        if slots.get("all_points"):
            tool_result = await _run_saved_points_blanks_report(user_id=user_id, period_hint=period_hint)
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"blanks_tool": tool_result})

        point_name = slots.get("point_name")
        logger.info("Blanks scenario execute user_id=%s point=%s period=%s", user_id, point_name, period_hint)
        if not point_name:
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"blanks_tool": {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}})
        db = get_db_session()
        try:
            system = _find_italian_pizza_system(db, user_id, point_name=point_name)
            if not system:
                result = {
                    "status": "system_not_connected",
                    "message": "Для этой точки не подключена система Italian Pizza. Сначала подключите панель управления, затем добавьте точку.",
                }
            else:
                result = await blanks_tool.inspect_point(
                    url=system.url or ITALIAN_PIZZA_PORTAL_URL,
                    username=system.login,
                    encrypted_password=system.encrypted_password,
                    point_name=point_name,
                    period_hint=period_hint,
                )
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"blanks_tool": result})
        finally:
            db.close()


class BrowserReportScenario(BaseScenario):
    name = "browser_report"
    selected_tools = ["browser_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        if not systems:
            result = {"connected_systems": 0, "systems": [], "status": "no_systems_connected"}
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"browser_tool": result})
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                result = {"connected_systems": 0, "systems": [], "status": "user_not_found"}
                return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"browser_tool": result})
            system = (
                db.query(DataAgentSystem)
                .filter(DataAgentSystem.user_id == user.id, DataAgentSystem.is_active == True)
                .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
                .first()
            )
            if not system:
                result = {"connected_systems": 0, "systems": [], "status": "system_not_found"}
                return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"browser_tool": result})
            try:
                data = await browser_agent.extract_data(
                    url=system.url,
                    username=system.login,
                    encrypted_password=system.encrypted_password,
                    user_task=user_message,
                    progress_callback=None,
                )
                result = {
                    "connected_systems": len(systems),
                    "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}],
                    "status": "completed",
                    "data": data,
                }
            except Exception as exc:
                logger.warning("Browser scenario fallback used: %s", exc)
                result = {
                    "connected_systems": len(systems),
                    "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}],
                    "status": "failed",
                    "error": str(exc),
                }
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"browser_tool": result})
        finally:
            db.close()


class GeneralScenario(BaseScenario):
    name = "general"
    selected_tools = ["orchestrator"]


class DataAgentScenarioEngine:
    def __init__(self) -> None:
        self._scenarios = {
            "general": GeneralScenario(),
            "browser_report": BrowserReportScenario(),
            "reviews_report": ReviewsReportScenario(),
            "stoplist_report": StoplistReportScenario(),
            "blanks_report": BlanksReportScenario(),
        }

    async def execute(self, *, scenario: str, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        handler = self._scenarios.get(scenario, self._scenarios["general"])
        execution = await handler.execute(user_id=user_id, user_message=user_message, slots=slots, systems=systems)
        if execution.answer:
            return execution
        if scenario in DIRECT_ANSWER_SCENARIOS:
            execution.answer = orchestrator._fallback_answer(execution.tool_results)
            return execution
        execution.answer = await orchestrator.synthesize(user_message, execution.tool_results)
        return execution


def _find_italian_pizza_system(db, user_id: int, *, point_name: str | None = None) -> Optional[DataAgentSystem]:
    user = db.query(User).filter(User.telegram_id == user_id).first()
    if not user:
        return None
    if point_name:
        normalized_point_name = " ".join((point_name or "").lower().split())
        saved_points = (
            db.query(SavedPoint)
            .filter(
                SavedPoint.user_id == user.id,
                SavedPoint.is_active == True,
                SavedPoint.provider == "italian_pizza",
            )
            .all()
        )
        matched_point = next(
            (
                point
                for point in saved_points
                if " ".join((point.display_name or "").lower().split()) == normalized_point_name
            ),
            None,
        )
        if matched_point and matched_point.system_id:
            system = (
                db.query(DataAgentSystem)
                .filter(
                    DataAgentSystem.id == matched_point.system_id,
                    DataAgentSystem.user_id == user.id,
                    DataAgentSystem.is_active == True,
                )
                .first()
            )
            if system:
                return system
    return (
        db.query(DataAgentSystem)
        .filter(
            DataAgentSystem.user_id == user.id,
            DataAgentSystem.is_active == True,
            (DataAgentSystem.system_name == "italian_pizza") | (DataAgentSystem.url.contains("italianpizza")),
        )
        .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
        .first()
    )


def _should_use_public_reviews_browser(user_message: str) -> bool:
    lowered = user_message.lower()
    return any(marker in lowered for marker in ["2гис", "2gis", "яндекс", "yandex", "карты", "картах", "maps"])


def _resolve_public_reviews_providers(user_message: str) -> list[str]:
    lowered = user_message.lower()
    mentions_2gis = any(marker in lowered for marker in ["2гис", "2gis"])
    mentions_yandex = any(marker in lowered for marker in ["яндекс", "yandex"])

    if any(marker in lowered for marker in ["только 2гис", "only 2gis", "лишь 2гис"]):
        return ["2gis"]
    if any(marker in lowered for marker in ["только яндекс", "only yandex", "лишь яндекс"]):
        return ["yandex_maps"]

    if mentions_2gis:
        return ["2gis"]
    if mentions_yandex:
        return ["yandex_maps"]
    return ["yandex_maps"]


def _result_text_or_fallback(result: dict, *, failure_text: str) -> str:
    status = str(result.get("status") or "").lower()
    if status in {"ok", "completed"}:
        return str(result.get("report_text") or "").strip() or "Отчёт собран."
    return failure_text


def _blanks_result_text_or_fallback(result: dict, *, failure_text: str) -> str:
    status = str(result.get("status") or "").lower()
    if status not in {"ok", "completed"}:
        return failure_text

    text = str(result.get("report_text") or "").strip()
    if text:
        return text
    if result.get("has_red_flags"):
        return "Есть красные бланки. Детали сейчас не удалось получить полностью, проверьте точку в Italian Pizza."
    return "Красных бланков не видно."


def _build_saved_points_blanks_text(
    *,
    period_hint: str,
    sections: list[str],
    checked_count: int,
    failed_points: list[str],
    red_points: list[str],
    total_count: int,
) -> str:
    header = [
        "Бланки по сохранённым точкам",
        f"Период: {period_hint}",
        f"Проверено: {checked_count} из {total_count}",
        f"Красные зоны: {len(red_points)}" if red_points else "Красные зоны: нет",
    ]
    if red_points:
        header.append("С красными бланками: " + "; ".join(red_points))
    if failed_points:
        header.append("Не удалось проверить: " + "; ".join(failed_points))

    body = "\n\n".join(sections).strip()
    return "\n".join(header).strip() + ("\n\n" + body if body else "")


async def _run_saved_points_stoplist_report(*, user_id: int) -> dict:
    db = get_db_session()
    try:
        points = saved_point_service.list_points(db, user_id)
    finally:
        db.close()

    if not points:
        return {
            "status": "needs_saved_points",
            "message": "Сначала добавьте хотя бы одну точку, чтобы собрать общий отчёт.",
        }

    sections: list[str] = []
    has_ok_results = False
    for point in points:
        result = await stoplist_tool.collect_for_point(
            url="",
            username="",
            encrypted_password="",
            point_name=point.display_name,
        )
        result = point_statistics_service.enrich_stoplist_report(user_id, point.display_name, result)
        text = _result_text_or_fallback(result, failure_text="Не удалось получить отчёт по этой точке.")
        if str(result.get("status") or "").lower() in {"ok", "completed"}:
            has_ok_results = True
        sections.append(f"{point.display_name}\n{text}")

    final_text = "\n\n".join(sections).strip()
    return {
        "status": "ok" if has_ok_results else "failed",
        "report_text": final_text or "Не удалось получить общий отчёт по точкам.",
    }


async def _run_saved_points_blanks_report(*, user_id: int, period_hint: str) -> dict:
    db = get_db_session()
    try:
        points = saved_point_service.list_points(db, user_id)
        if not points:
            return {
                "status": "needs_saved_points",
                "message": "Сначала добавьте хотя бы одну точку, чтобы собрать общий отчёт.",
            }

        sections: list[str] = []
        checked_count = 0
        failed_points: list[str] = []
        red_points: list[str] = []
        for point in points:
            system = _find_italian_pizza_system(db, user_id, point_name=point.display_name)
            if not system:
                result = {
                    "status": "system_not_connected",
                }
            else:
                result = await blanks_tool.inspect_point(
                    url=system.url or ITALIAN_PIZZA_PORTAL_URL,
                    username=system.login,
                    encrypted_password=system.encrypted_password,
                    point_name=point.display_name,
                    period_hint=period_hint,
                )
            is_ok_result = str(result.get("status") or "").lower() in {"ok", "completed"}
            if is_ok_result:
                checked_count += 1
            else:
                failed_points.append(point.display_name)
            if result.get("has_red_flags"):
                red_points.append(point.display_name)
            text = _blanks_result_text_or_fallback(result, failure_text="Не удалось проверить эту точку. Попробуйте позже.")
            sections.append(f"{point.display_name}\n{text}")

        final_text = _build_saved_points_blanks_text(
            period_hint=period_hint,
            sections=sections,
            checked_count=checked_count,
            failed_points=failed_points,
            red_points=red_points,
            total_count=len(points),
        )
        return {
            "status": "ok" if checked_count else "failed",
            "report_text": final_text or "Не удалось получить общий отчёт по точкам.",
            "has_red_flags": bool(red_points),
            "checked_points": checked_count,
            "failed_points": failed_points,
            "red_points": red_points,
            "total_points": len(points),
        }
    finally:
        db.close()


def _provider_label(provider: str) -> str:
    return "2GIS" if provider == "2gis" else "Яндекс Карты"


def _is_access_denied_payload(payload: str) -> bool:
    lowered = (payload or "").lower()
    return "ошибка_доступа" in lowered or "access denied" in lowered or "отказ" in lowered


async def _run_public_reviews_browser(user_message: str, targets: List[str], providers: List[str] | None = None) -> dict:
    logger.info("Public reviews resolution message=%s targets=%s", user_message[:300], targets)
    providers = providers or _resolve_public_reviews_providers(user_message)
    results: List[dict] = []
    for target in targets[:5]:
        for provider in providers:
            if target.startswith("http://") or target.startswith("https://"):
                target_url = target
                target_label = target
            else:
                target_url = f"https://2gis.ru/search/{quote(target)}" if provider == "2gis" else f"https://yandex.ru/maps/?text={quote(target)}"
                target_label = target
            task_text = (
                "Собери краткий отчет по отзывам для этой точки. "
                "Главный акцент делай на критических отзывах с оценкой ниже 4 звёзд. "
                "Похвалы и позитивные детали не перечисляй, если нет риска или явной проблемы. "
                "Если критических отзывов за нужный период нет, так и напиши. "
                "Если видна средняя оценка, можешь указать её одной строкой.\n\n"
                f"Источник: {_provider_label(provider)}\n"
                f"Точка: {target_label}\n"
                f"Исходный запрос пользователя: {user_message}"
            )
            try:
                logger.info("Public reviews browser run target=%s url=%s provider=%s", target_label, target_url, provider)
                data = await browser_agent.extract_data(
                    url=target_url,
                    username=None,
                    encrypted_password=None,
                    user_task=task_text,
                    progress_callback=None,
                )
                results.append(
                    {
                        "target": target_label,
                        "provider": provider,
                        "url": target_url,
                        "status": "ok",
                        "data": data,
                        "access_denied": _is_access_denied_payload(str(data)),
                    }
                )
            except Exception as exc:
                logger.warning("Public reviews browser failed target=%s provider=%s error=%s", target_label, provider, exc)
                results.append(
                    {
                        "target": target_label,
                        "provider": provider,
                        "url": target_url,
                        "status": "error",
                        "error": str(exc),
                    }
                )
    ok_results = [item for item in results if item["status"] == "ok" and not item.get("access_denied")]
    if not ok_results:
        return {
            "status": "not_configured",
            "message": "Отчёт по отзывам для этой точки пока недоступен.",
            "targets": results,
        }
    report_lines = ["Отчёт по отзывам по точкам:"]
    for target_label in list(dict.fromkeys(item["target"] for item in ok_results)):
        report_lines.append(f"\nТочка: {target_label}")
        for item in [candidate for candidate in ok_results if candidate["target"] == target_label]:
            provider_label = _provider_label(item["provider"])
            report_lines.append(f"{provider_label}:\n{item['data']}")
    failed_providers = [
        {
            "target": item["target"],
            "provider": item["provider"],
            "reason": item.get("error") or item.get("data") or "",
        }
        for item in results
        if item.get("status") != "ok" or item.get("access_denied")
    ]
    return {
        "status": "ok",
        "source": "public_maps_multi",
        "providers": providers,
        "targets": results,
        "failed_providers": failed_providers,
        "report_text": "\n".join(report_lines).strip(),
    }


scenario_engine = DataAgentScenarioEngine()

