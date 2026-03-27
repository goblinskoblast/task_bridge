from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from bot.ai_provider import get_ai_provider

from .prompts import (
    DATA_AGENT_SYNTHESIS_PROMPT,
    DATA_AGENT_TOOL_PLAN_PROMPT,
    build_synthesis_user_prompt,
    build_tool_plan_user_prompt,
)

logger = logging.getLogger(__name__)

KNOWN_TOOLS = {"email_tool", "calendar_tool", "browser_tool", "orchestrator"}


@dataclass
class OrchestratorPlan:
    selected_tools: List[str]
    reasoning: str
    response_style: str = "brief"


class DataAgentOrchestrator:
    async def plan(self, user_message: str, systems_count: int = 0) -> OrchestratorPlan:
        fallback_plan = self._fallback_plan(user_message)
        try:
            provider = get_ai_provider()
            result = await provider.analyze_message(
                messages=[
                    {"role": "system", "content": DATA_AGENT_TOOL_PLAN_PROMPT},
                    {"role": "user", "content": build_tool_plan_user_prompt(user_message, systems_count)},
                ],
                temperature=0.1,
                max_tokens=350,
                response_format={"type": "json_object"},
            )
            return self._normalize_plan(result, fallback_plan)
        except Exception as exc:
            logger.warning("DataAgent orchestrator fallback plan used: %s", exc)
            return fallback_plan

    async def synthesize(self, user_message: str, tool_results: Dict[str, Any]) -> str:
        try:
            provider = get_ai_provider()
            result = await provider.analyze_message(
                messages=[
                    {"role": "system", "content": DATA_AGENT_SYNTHESIS_PROMPT},
                    {"role": "user", "content": build_synthesis_user_prompt(user_message, tool_results)},
                ],
                temperature=0.2,
                max_tokens=700,
            )

            if isinstance(result, dict):
                content = result.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

            if isinstance(result, str) and result.strip():
                return result.strip()
        except Exception as exc:
            logger.warning("DataAgent synthesis fallback used: %s", exc)

        return self._fallback_answer(tool_results)

    def _normalize_plan(self, result: Any, fallback_plan: OrchestratorPlan) -> OrchestratorPlan:
        if not isinstance(result, dict):
            return fallback_plan

        raw_tools = result.get("selected_tools")
        if not isinstance(raw_tools, list):
            return fallback_plan

        selected_tools = [tool for tool in raw_tools if tool in KNOWN_TOOLS]
        if not selected_tools:
            selected_tools = fallback_plan.selected_tools

        reasoning = str(result.get("reasoning", fallback_plan.reasoning)).strip() or fallback_plan.reasoning
        response_style = str(result.get("response_style", "brief")).strip() or "brief"
        return OrchestratorPlan(selected_tools=selected_tools, reasoning=reasoning, response_style=response_style)

    def _fallback_plan(self, message: str) -> OrchestratorPlan:
        lowered = message.lower()
        tools: List[str] = []

        if any(token in lowered for token in ["почт", "письм", "mail", "email", "gmail", "яндекс"]):
            tools.append("email_tool")
        if any(token in lowered for token in ["календар", "calendar", "встреч", "созвон", "meeting", "call", "deadline", "schedule"]):
            tools.append("calendar_tool")
        if any(token in lowered for token in ["выручк", "erp", "crm", "отчет", "отчёт", "report", "dashboard", "iiko", "1c", "1с", "система"]):
            tools.append("browser_tool")

        if not tools:
            tools.append("orchestrator")

        return OrchestratorPlan(selected_tools=tools, reasoning="Fallback routing by keywords.")

    def _fallback_answer(self, tool_results: Dict[str, Any]) -> str:
        parts: List[str] = []

        email_result = tool_results.get("email_tool")
        if email_result:
            parts.append(
                "Почта:\n"
                f"- Подключённых аккаунтов: {email_result.get('accounts_count', 0)}\n"
                f"- Писем за период: {email_result.get('messages_count', 0)}"
            )

        calendar_result = tool_results.get("calendar_tool")
        if calendar_result:
            lines = [f"- Событий за период: {calendar_result.get('events_count', 0)}"]
            for item in calendar_result.get("events", [])[:5]:
                lines.append(f"- {item.get('start_at')}: {item.get('title')}")
            parts.append("Календарь:\n" + "\n".join(lines))

        browser_result = tool_results.get("browser_tool")
        if browser_result:
            if browser_result.get("connected_systems", 0) > 0:
                parts.append(
                    f"Внешние системы: подключено {browser_result.get('connected_systems', 0)}. "
                    "Browser Tool будет активирован на следующем этапе."
                )
            else:
                parts.append("Внешние системы пока не подключены. Используйте /connect.")

        if not parts:
            parts.append("DataAgent пока не собрал полезных данных по этому запросу.")

        return "\n\n".join(parts)


orchestrator = DataAgentOrchestrator()
