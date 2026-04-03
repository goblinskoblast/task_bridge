from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bot.ai_provider import get_ai_provider
from db.database import get_db_session
from db.models import DataAgentSession, User

from .italian_pizza import resolve_italian_pizza_point

logger = logging.getLogger(__name__)

SCENARIO_TOOL_MAP = {
    "general": ["orchestrator"],
    "browser_report": ["browser_tool"],
    "reviews_report": ["review_tool"],
    "stoplist_report": ["stoplist_tool"],
    "blanks_report": ["blanks_tool"],
}

FOLLOWUP_MARKERS = (
    "по этой точке",
    "по ней",
    "по этому адресу",
    "за предыдущие",
    "за последние",
    "прошлые",
    "предыдущие",
    "тот же",
    "та же",
    "это же",
)


@dataclass
class AgentSessionSnapshot:
    user_id: int
    scenario: str = "general"
    status: str = "idle"
    slots: Dict[str, Any] = field(default_factory=dict)
    last_selected_tools: List[str] = field(default_factory=list)
    last_user_message: str = ""
    last_answer: str = ""


@dataclass
class AgentDecision:
    scenario: str
    selected_tools: List[str]
    slots: Dict[str, Any]
    missing_slots: List[str]
    reasoning: str
    response_style: str = "brief"


class DataAgentRuntime:
    async def decide(self, user_id: int, message: str, systems_count: int = 0) -> AgentDecision:
        session = self.load_session(user_id)
        rule_decision = self._rule_based_decision(message, session, systems_count)
        llm_decision = await self._llm_decision(message, session, systems_count)
        return self._merge_decisions(rule_decision, llm_decision, session)

    def load_session(self, user_id: int) -> AgentSessionSnapshot:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return AgentSessionSnapshot(user_id=user_id)
            session = db.query(DataAgentSession).filter(DataAgentSession.user_id == user.id).first()
            if not session:
                return AgentSessionSnapshot(user_id=user_id)
            return AgentSessionSnapshot(
                user_id=user_id,
                scenario=session.active_scenario or "general",
                status=session.status or "idle",
                slots=session.slots_json or {},
                last_selected_tools=session.last_selected_tools or [],
                last_user_message=session.last_user_message or "",
                last_answer=session.last_answer or "",
            )
        finally:
            db.close()

    def save_session(self, user_id: int, decision: AgentDecision, *, user_message: str, answer: str = "", status: str = "completed") -> None:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                user = User(telegram_id=user_id, username=None, first_name=None, last_name=None, is_bot=False)
                db.add(user)
                db.flush()
            session = db.query(DataAgentSession).filter(DataAgentSession.user_id == user.id).first()
            if not session:
                session = DataAgentSession(user_id=user.id)
                db.add(session)
            session.active_scenario = decision.scenario
            session.status = status
            session.slots_json = decision.slots
            session.last_selected_tools = decision.selected_tools
            session.last_user_message = user_message
            if answer:
                session.last_answer = answer
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to save data-agent session")
        finally:
            db.close()

    def _merge_decisions(self, rule_decision: AgentDecision, llm_decision: Optional[AgentDecision], session: AgentSessionSnapshot) -> AgentDecision:
        base = llm_decision or rule_decision
        if rule_decision.scenario != "general":
            base = rule_decision
        merged_slots = dict(session.slots or {})
        merged_slots.update(base.slots or {})
        source_message = str(base.slots.get("source_message") or "")
        if not merged_slots.get("point_name") and self._is_followup(source_message, session):
            if session.slots.get("point_name"):
                merged_slots["point_name"] = session.slots.get("point_name")
        if not merged_slots.get("period_hint") and base.scenario == session.scenario and session.slots.get("period_hint"):
            merged_slots["period_hint"] = session.slots.get("period_hint")
        required = self._required_slots(base.scenario)
        missing = [slot for slot in required if not merged_slots.get(slot)]
        return AgentDecision(
            scenario=base.scenario,
            selected_tools=SCENARIO_TOOL_MAP.get(base.scenario, ["orchestrator"]),
            slots=merged_slots,
            missing_slots=missing,
            reasoning=base.reasoning,
            response_style=base.response_style,
        )

    def _rule_based_decision(self, message: str, session: AgentSessionSnapshot, systems_count: int) -> AgentDecision:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        scenario = "general"
        reasoning = "Rule-based routing"
        if any(token in lowered for token in ["стоп-лист", "стоп лист", "недоступн", "нет в наличии"]):
            scenario = "stoplist_report"
            reasoning = "Определен сценарий стоп-листа"
        elif any(token in lowered for token in ["бланк загрузки", "бланки загрузки", "перегруз", "красн", "лимит", "норматив"]):
            scenario = "blanks_report"
            reasoning = "Определен сценарий бланков"
        elif any(token in lowered for token in ["отзыв", "отзывы", "рейтинг", "2гис", "2gis", "яндекс карты"]):
            scenario = "reviews_report"
            reasoning = "Определен сценарий отзывов"
        elif systems_count > 0 and any(token in lowered for token in ["сайт", "кабинет", "crm", "dashboard", "отчет", "отчёт", "внешн"]):
            scenario = "browser_report"
            reasoning = "Определен сценарий внешней системы"
        elif self._is_followup(message, session):
            scenario = session.scenario or "general"
            reasoning = f"Follow-up продолжает сценарий {scenario}"
        slots = self._extract_slots(message, session)
        slots["source_message"] = message
        if scenario == "blanks_report" and not slots.get("period_hint"):
            slots["period_hint"] = session.slots.get("period_hint") or "текущий бланк"
        missing = [slot for slot in self._required_slots(scenario) if not slots.get(slot)]
        return AgentDecision(
            scenario=scenario,
            selected_tools=SCENARIO_TOOL_MAP.get(scenario, ["orchestrator"]),
            slots=slots,
            missing_slots=missing,
            reasoning=reasoning,
        )

    async def _llm_decision(self, message: str, session: AgentSessionSnapshot, systems_count: int) -> Optional[AgentDecision]:
        provider = get_ai_provider()
        prompt = (
            "Ты интерпретатор запросов data-agent. Верни только JSON. "
            "Сценарии: general, browser_report, reviews_report, stoplist_report, blanks_report. "
            "Вытащи scenario, point_name, period_hint, reasoning. Если не уверен, используй general."
        )
        user_prompt = {
            "message": message,
            "systems_count": systems_count,
            "session": {"scenario": session.scenario, "slots": session.slots, "last_selected_tools": session.last_selected_tools},
        }
        try:
            result = await provider.analyze_message(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
                temperature=0.1,
                max_tokens=250,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("DataAgentRuntime llm decision fallback used: %s", exc)
            return None
        scenario = str(result.get("scenario") or "general").strip()
        if scenario not in SCENARIO_TOOL_MAP:
            scenario = "general"
        slots = self._extract_slots(message, session)
        if result.get("point_name"):
            slots["point_name"] = str(result["point_name"]).strip()
        if result.get("period_hint"):
            slots["period_hint"] = str(result["period_hint"]).strip()
        slots["source_message"] = message
        missing = [slot for slot in self._required_slots(scenario) if not slots.get(slot)]
        return AgentDecision(
            scenario=scenario,
            selected_tools=SCENARIO_TOOL_MAP.get(scenario, ["orchestrator"]),
            slots=slots,
            missing_slots=missing,
            reasoning=str(result.get("reasoning") or "LLM routing").strip(),
        )

    def _extract_slots(self, message: str, session: AgentSessionSnapshot) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}
        point = resolve_italian_pizza_point(message)
        if point:
            slots["point_name"] = point.display_name
        period = self._extract_period_hint(message)
        if period:
            slots["period_hint"] = period
        interval = self._extract_monitor_interval(message)
        if interval:
            slots["monitor_interval_minutes"] = interval
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if any(marker in lowered for marker in FOLLOWUP_MARKERS) and session.slots.get("point_name"):
            slots.setdefault("point_name", session.slots.get("point_name"))
        return slots

    def _extract_period_hint(self, message: str) -> Optional[str]:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if "12 часов" in lowered or "предыдущие 12" in lowered:
            return "предыдущие 12 часов"
        if "3 часа" in lowered or "три час" in lowered or "предыдущие 3" in lowered:
            return "предыдущие 3 часа"
        if "сутки" in lowered or "24 часа" in lowered:
            return "последние сутки"
        if "сегодня" in lowered:
            return "сегодня"
        if "текущий бланк" in lowered:
            return "текущий бланк"
        return None

    def _extract_monitor_interval(self, message: str) -> Optional[int]:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if "раз в час" in lowered or "каждый час" in lowered:
            return 60
        if "раз в три часа" in lowered or "каждые три часа" in lowered:
            return 180
        match = re.search(r"каждые\s+(\d+)\s+час", lowered)
        if match:
            return int(match.group(1)) * 60
        return None

    def _required_slots(self, scenario: str) -> List[str]:
        if scenario in {"stoplist_report", "blanks_report"}:
            return ["point_name"]
        return []

    def _is_followup(self, message: str, session: AgentSessionSnapshot) -> bool:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if any(marker in lowered for marker in FOLLOWUP_MARKERS):
            return True
        if session.scenario in {"stoplist_report", "blanks_report", "reviews_report"} and len(lowered) < 120 and resolve_italian_pizza_point(message):
            return True
        return False

    def build_missing_slots_answer(self, decision: AgentDecision) -> str:
        if "point_name" in decision.missing_slots:
            if decision.scenario == "stoplist_report":
                return "Не хватает точки для стоп-листа. Пришли город и адрес пиццерии одним сообщением."
            if decision.scenario == "blanks_report":
                return "Не хватает точки для бланков загрузки. Пришли город и адрес пиццерии одним сообщением."
            return "Не хватает точки. Пришли город и адрес пиццерии одним сообщением."
        return "Нужны дополнительные данные для выполнения запроса."


agent_runtime = DataAgentRuntime()
