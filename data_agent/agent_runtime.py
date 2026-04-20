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
    "monitor_management": ["orchestrator"],
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

MONITOR_INTENT_MARKERS = (
    "присылай",
    "мониторь",
    "мониторинг",
    "следи",
    "уведомляй",
)

MONITOR_DISABLE_MARKERS = (
    "не присылай",
    "больше не присылай",
    "перестань присылать",
    "отключи",
    "выключи",
    "останови мониторинг",
    "убери мониторинг",
    "отмени мониторинг",
)

MONITOR_UPDATE_MARKERS = (
    "измени",
    "поменяй",
    "обнови",
    "перенастрой",
    "настрой",
    "поставь",
    "сделай",
)

MONITOR_SETTINGS_MARKERS = (
    "мониторинг",
    "рассыл",
    "уведомлен",
    "уведомлени",
    "присылай",
    "следи",
    "окно",
    "интервал",
    "расписан",
    "время",
)

MONITOR_LIST_MARKERS = (
    "какие мониторинги",
    "какие у меня мониторинги",
    "покажи мониторинги",
    "покажи мои мониторинги",
    "покажи активные мониторинги",
    "список мониторингов",
    "активные мониторинги",
    "мои мониторинги",
    "что у меня включено",
    "что сейчас включено",
    "что включено",
    "что включено по мониторингам",
    "что присылается",
    "что ты присылаешь",
    "какие отчеты присылаются",
    "какие отчёты присылаются",
    "какие рассылки",
    "активные рассылки",
    "активные уведомления",
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
        if self._should_skip_llm_routing(rule_decision):
            return self._merge_decisions(rule_decision, None, session)
        llm_decision = await self._llm_decision(message, session, systems_count)
        return self._merge_decisions(rule_decision, llm_decision, session)

    def decide_fast(self, user_id: int, message: str, systems_count: int = 0) -> AgentDecision:
        session = self.load_session(user_id)
        rule_decision = self._rule_based_decision(message, session, systems_count)
        return self._merge_decisions(rule_decision, None, session)

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

    def save_session(
        self,
        user_id: int,
        decision: AgentDecision,
        *,
        user_message: str,
        answer: str = "",
        status: str = "completed",
        trace_id: str | None = None,
        debug_summary: str | None = None,
        debug_payload: Dict[str, Any] | None = None,
    ) -> None:
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
            session.last_trace_id = trace_id
            session.last_debug_summary = debug_summary
            session.last_debug_payload = debug_payload
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
        source_message = str(base.slots.get("source_message") or "")
        same_scenario = bool(base.scenario and base.scenario == session.scenario)
        followup_request = self._is_followup(source_message, session)

        merged_slots = dict(base.slots or {})
        if not merged_slots.get("point_name") and not merged_slots.get("all_points") and followup_request:
            if session.slots.get("point_name"):
                merged_slots["point_name"] = session.slots.get("point_name")
        if not merged_slots.get("period_hint") and followup_request and same_scenario and session.slots.get("period_hint"):
            merged_slots["period_hint"] = session.slots.get("period_hint")
        if not merged_slots.get("monitor_interval_minutes") and same_scenario and session.slots.get("monitor_interval_minutes"):
            merged_slots["monitor_interval_minutes"] = session.slots.get("monitor_interval_minutes")
        if merged_slots.get("monitor_interval_minutes") and not merged_slots.get("monitor_interval_source") and session.slots.get("monitor_interval_source"):
            merged_slots["monitor_interval_source"] = session.slots.get("monitor_interval_source")
        required = self._required_slots(base.scenario, merged_slots)
        if merged_slots.get("all_points") and "point_name" in required:
            required = [slot for slot in required if slot != "point_name"]
        missing = [slot for slot in required if not merged_slots.get(slot)]
        return AgentDecision(
            scenario=base.scenario,
            selected_tools=SCENARIO_TOOL_MAP.get(base.scenario, ["orchestrator"]),
            slots=merged_slots,
            missing_slots=missing,
            reasoning=base.reasoning,
            response_style=base.response_style,
        )

    def _should_skip_llm_routing(self, rule_decision: AgentDecision) -> bool:
        return rule_decision.scenario != "general"

    def _rule_based_decision(self, message: str, session: AgentSessionSnapshot, systems_count: int) -> AgentDecision:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        scenario = "general"
        reasoning = "Rule-based routing"
        monitor_action = self._extract_monitor_action(lowered)
        if self._has_monitor_list_intent(lowered):
            scenario = "monitor_management"
            reasoning = "Запрошен список мониторингов"
        elif self._contains_stoplist_intent(lowered):
            scenario = "stoplist_report"
            reasoning = "Определен сценарий стоп-листа"
        elif any(token in lowered for token in ["бланк загрузки", "бланки загрузки", "бланк", "бланки", "перегруз", "красн", "лимит", "норматив"]):
            scenario = "blanks_report"
            reasoning = "Определен сценарий бланков"
        elif any(token in lowered for token in ["отзыв", "отзывы", "рейтинг", "2гис", "2gis", "яндекс карты"]):
            scenario = "reviews_report"
            reasoning = "Определен сценарий отзывов"
        elif monitor_action == "update" and self._looks_like_generic_monitor_update(lowered, message):
            scenario = "monitor_management"
            reasoning = "Запрошено изменение настроек мониторинга без ID"
        elif monitor_action == "disable" and self._looks_like_generic_monitor_disable(lowered, message):
            scenario = "monitor_management"
            reasoning = "Запрошено отключение мониторинга без ID"
        elif self._is_point_only_followup(message, session):
            scenario = session.scenario or "general"
            reasoning = f"Точка обновляет текущий сценарий {scenario}"
        elif systems_count > 0 and any(token in lowered for token in ["сайт", "кабинет", "crm", "dashboard", "отчет", "отчёт", "внешн"]):
            scenario = "browser_report"
            reasoning = "Определен сценарий внешней системы"
        elif self._is_followup(message, session):
            scenario = session.scenario or "general"
            reasoning = f"Follow-up продолжает сценарий {scenario}"
        slots = self._extract_slots(message, session)
        slots["source_message"] = message
        monitor_action = slots.get("monitor_action")
        if scenario in {"blanks_report", "stoplist_report"} and monitor_action != "disable" and not slots.get("monitor_interval_minutes"):
            if self._has_monitor_intent(lowered):
                slots["monitor_interval_minutes"] = 180
                slots["monitor_interval_source"] = "default_intent"
        if scenario == "blanks_report" and monitor_action != "disable" and not slots.get("period_hint"):
            slots["period_hint"] = "за последние 3 часа"
        required = self._required_slots(scenario, slots)
        if slots.get("all_points") and "point_name" in required:
            required = [slot for slot in required if slot != "point_name"]
        missing = [slot for slot in required if not slots.get(slot)]
        return AgentDecision(
            scenario=scenario,
            selected_tools=SCENARIO_TOOL_MAP.get(scenario, ["orchestrator"]),
            slots=slots,
            missing_slots=missing,
            reasoning=reasoning,
        )

    def _contains_stoplist_intent(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "стоп-лист",
                "стоп лист",
                "стоплист",
                "по стопам",
                "стопы",
                "стопам",
                "стопах",
                "недоступн",
                "нет в наличии",
            ]
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
        required = self._required_slots(scenario, slots)
        if slots.get("all_points") and "point_name" in required:
            required = [slot for slot in required if slot != "point_name"]
        missing = [slot for slot in required if not slots.get(slot)]
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
        if self._is_all_points_request(message):
            slots["all_points"] = True
        period = self._extract_period_hint(message)
        if period:
            slots["period_hint"] = period
        interval = self._extract_monitor_interval(message)
        if interval:
            slots["monitor_interval_minutes"] = interval
            slots["monitor_interval_source"] = "explicit"
        window = self._extract_monitor_window(message)
        if window:
            start_hour, end_hour = window
            slots["monitor_start_hour"] = start_hour
            slots["monitor_end_hour"] = end_hour
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        monitor_action = self._extract_monitor_action(lowered)
        if monitor_action:
            slots["monitor_action"] = monitor_action
        if any(marker in lowered for marker in FOLLOWUP_MARKERS) and session.slots.get("point_name") and not slots.get("all_points"):
            slots.setdefault("point_name", session.slots.get("point_name"))
        return slots

    def _extract_period_hint(self, message: str) -> Optional[str]:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if "текущий бланк" in lowered:
            return "текущий бланк"
        if "вчера" in lowered:
            return "вчера"
        if "сегодня" in lowered:
            return "сегодня"
        if any(marker in lowered for marker in ["сутки", "24 часа", "за день", "за последний день", "последний день"]):
            return "последние сутки"
        if any(marker in lowered for marker in ["за неделю", "за последнюю неделю", "последняя неделя", "за 7 дней", "последние 7 дней", "еженедель"]):
            return "за последнюю неделю"

        hours_match = re.search(r"(?:за|последние|предыдущие)?\s*(\d+)\s*час", lowered)
        if hours_match:
            hours = int(hours_match.group(1))
            if hours == 24:
                return "последние сутки"
            if hours > 0:
                return f"за последние {hours} {self._hours_word(hours)}"

        if "три часа" in lowered:
            return "за последние 3 часа"
        if "шесть часов" in lowered:
            return "за последние 6 часов"
        if "двенадцать часов" in lowered:
            return "за последние 12 часов"
        if "пятнадцать часов" in lowered:
            return "за последние 15 часов"
        return None

    def _hours_word(self, hours: int) -> str:
        remainder_10 = hours % 10
        remainder_100 = hours % 100
        if remainder_10 == 1 and remainder_100 != 11:
            return "час"
        if remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
            return "часа"
        return "часов"

    def _extract_monitor_interval(self, message: str) -> Optional[int]:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if "раз в час" in lowered or "каждый час" in lowered:
            return 60
        if "раз в три часа" in lowered or "каждые три часа" in lowered:
            return 180
        if any(marker in lowered for marker in ["каждый день", "ежедневно", "раз в день", "раз в сутки", "каждые сутки"]):
            return 1440
        match = re.search(r"каждые\s+(\d+)\s+час", lowered)
        if match:
            return int(match.group(1)) * 60
        return None

    def _has_monitor_intent(self, lowered: str) -> bool:
        return any(marker in lowered for marker in MONITOR_INTENT_MARKERS)

    def _has_monitor_list_intent(self, lowered: str) -> bool:
        if any(marker in lowered for marker in MONITOR_LIST_MARKERS):
            return True
        if "мониторинг" in lowered and any(
            marker in lowered
            for marker in (
                "какие",
                "покажи",
                "список",
                "активные",
                "включено",
                "включены",
                "включённые",
                "включенные",
            )
        ):
            return True
        if any(marker in lowered for marker in ("какие", "что", "покажи")) and any(
            marker in lowered for marker in ("присыла", "рассыл", "уведомлен")
        ):
            return True
        return False

    def _looks_like_generic_monitor_disable(self, lowered: str, message: str) -> bool:
        if any(marker in lowered for marker in ("мониторинг", "рассыл", "уведомлен", "уведомлени", "уведомления")):
            return True
        return resolve_italian_pizza_point(message) is not None

    def _looks_like_generic_monitor_update(self, lowered: str, message: str) -> bool:
        if any(marker in lowered for marker in MONITOR_SETTINGS_MARKERS):
            return True
        return resolve_italian_pizza_point(message) is not None

    def _extract_monitor_action(self, lowered: str) -> Optional[str]:
        if self._has_monitor_list_intent(lowered):
            return "list"
        if any(marker in lowered for marker in MONITOR_DISABLE_MARKERS):
            return "disable"
        if any(marker in lowered for marker in MONITOR_UPDATE_MARKERS) and any(
            marker in lowered for marker in MONITOR_SETTINGS_MARKERS
        ):
            return "update"
        return None

    def _extract_monitor_window(self, message: str) -> Optional[tuple[int, int]]:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        patterns = (
            r"с\s*(\d{1,2})(?::\d{2})?\s*(?:утра|дня|вечера|ночи)?\s*(?:до|по)\s*(\d{1,2})(?::\d{2})?\s*(?:утра|дня|вечера|ночи)?",
            r"(\d{1,2})\s*(?:-|–|—)\s*(\d{1,2})",
        )
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            start_hour = int(match.group(1))
            end_hour = int(match.group(2))
            if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
                return None
            return start_hour, end_hour
        return None

    def _is_all_points_request(self, message: str) -> bool:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        markers = (
            "все точки",
            "по всем точкам",
            "по всем добавленным точкам",
            "все добавленные точки",
            "по добавленным точкам",
        )
        return any(marker in lowered for marker in markers)

    def _required_slots(self, scenario: str, slots: Dict[str, Any] | None = None) -> List[str]:
        if scenario == "monitor_management" and slots and slots.get("monitor_action") in {"disable", "update"}:
            return ["point_name"]
        if scenario in {"stoplist_report", "blanks_report"}:
            return ["point_name"]
        return []

    def _is_point_only_followup(self, message: str, session: AgentSessionSnapshot) -> bool:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if session.scenario not in {"stoplist_report", "blanks_report", "reviews_report"}:
            return False
        if not resolve_italian_pizza_point(message):
            return False
        scenario_markers = ["стоп", "бланк", "отзыв", "рейтинг", "карты", "сайт", "кабинет"]
        if any(marker in lowered for marker in scenario_markers):
            return False
        return len(lowered) <= 120

    def _is_followup(self, message: str, session: AgentSessionSnapshot) -> bool:
        lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
        if any(marker in lowered for marker in FOLLOWUP_MARKERS):
            return True
        if self._is_point_only_followup(message, session):
            return True
        return False

    def build_missing_slots_answer(self, decision: AgentDecision) -> str:
        if "point_name" in decision.missing_slots:
            if decision.scenario == "monitor_management":
                return "Не хватает точки для отключения мониторинга. Пришли город и адрес пиццерии одним сообщением."
            if decision.scenario == "stoplist_report":
                return "Не хватает точки для стоп-листа. Пришли город и адрес пиццерии одним сообщением."
            if decision.scenario == "blanks_report":
                return "Не хватает точки для бланков загрузки. Пришли город и адрес пиццерии одним сообщением."
            return "Не хватает точки. Пришли город и адрес пиццерии одним сообщением."
        return "Нужны дополнительные данные для выполнения запроса."


agent_runtime = DataAgentRuntime()
