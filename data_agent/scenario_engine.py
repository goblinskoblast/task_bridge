from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote

from db.database import get_db_session
from db.models import DataAgentSystem, User

from .blanks_tool import blanks_tool
from .browser_agent import browser_agent
from .italian_pizza import ITALIAN_PIZZA_PORTAL_URL
from .models import ConnectedSystem
from .orchestrator import orchestrator
from .review_report import review_report_service
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
            tool_result = await review_report_service.build_report(user_message, point_name=point_name)
            if tool_result.get("status") == "not_configured":
                if point_name:
                    tool_result = await _run_public_reviews_browser(user_message, targets=[point_name])
                else:
                    tool_result = {
                        "status": "needs_point",
                        "message": "Чтобы собрать отзывы без подключённой таблицы, укажите конкретную точку.",
                    }
        return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"review_tool": tool_result})


class StoplistReportScenario(BaseScenario):
    name = "stoplist_report"
    selected_tools = ["stoplist_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        point_name = slots.get("point_name")
        logger.info("Stoplist scenario execute user_id=%s point=%s", user_id, point_name)
        if not point_name:
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"stoplist_tool": {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}})
        tool_result = await stoplist_tool.collect_for_point(url="", username="", encrypted_password="", point_name=point_name)
        return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"stoplist_tool": tool_result})


class BlanksReportScenario(BaseScenario):
    name = "blanks_report"
    selected_tools = ["blanks_tool"]

    async def execute(self, *, user_id: int, user_message: str, slots: dict, systems: List[ConnectedSystem]) -> ScenarioExecution:
        point_name = slots.get("point_name")
        period_hint = slots.get("period_hint") or "текущий бланк"
        logger.info("Blanks scenario execute user_id=%s point=%s period=%s", user_id, point_name, period_hint)
        if not point_name:
            return ScenarioExecution(selected_tools=list(self.selected_tools), tool_results={"blanks_tool": {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}})
        db = get_db_session()
        try:
            system = _find_italian_pizza_system(db, user_id)
            if not system:
                result = {"status": "system_not_connected", "message": "Italian Pizza портал ещё не подключён. Используйте /connect для tochka.italianpizza.ru."}
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


def _find_italian_pizza_system(db, user_id: int) -> Optional[DataAgentSystem]:
    user = db.query(User).filter(User.telegram_id == user_id).first()
    if not user:
        return None
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


async def _run_public_reviews_browser(user_message: str, targets: List[str]) -> dict:
    logger.info("Public reviews resolution message=%s targets=%s", user_message[:300], targets)
    lowered = user_message.lower()
    provider = "2gis" if ("2гис" in lowered or "2gis" in lowered) else "yandex_maps"
    results: List[dict] = []
    for target in targets[:5]:
        if target.startswith("http://") or target.startswith("https://"):
            target_url = target
            target_label = target
        else:
            target_url = f"https://2gis.ru/search/{quote(target)}" if provider == "2gis" else f"https://yandex.ru/maps/?text={quote(target)}"
            target_label = target
        task_text = (
            "Собери краткий отчет по отзывам для этой точки. Найди свежие отзывы, общую тональность, основные жалобы, основные похвалы и если возможно укажи среднюю оценку. Ответ верни кратко и по делу.\n\n"
            f"Точка: {target_label}\nИсходный запрос пользователя: {user_message}"
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
            results.append({"target": target_label, "url": target_url, "status": "ok", "data": data})
        except Exception as exc:
            logger.warning("Public reviews browser failed target=%s error=%s", target_label, exc)
            results.append({"target": target_label, "url": target_url, "status": "error", "error": str(exc)})
    ok_results = [item for item in results if item["status"] == "ok"]
    if not ok_results:
        return {"status": "failed", "message": "Не удалось собрать отзывы по переданным точкам.", "targets": results}
    report_lines = ["Отчет по отзывам по точкам:"]
    for item in ok_results:
        report_lines.append(f"\nТочка: {item['target']}\n{item['data']}")
    return {"status": "ok", "source": provider, "targets": results, "report_text": "\n".join(report_lines).strip()}


scenario_engine = DataAgentScenarioEngine()
