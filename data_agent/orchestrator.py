from __future__ import annotations

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

KNOWN_TOOLS = {"email_tool", "calendar_tool", "browser_tool", "review_tool", "orchestrator"}


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

        review_keywords = [
            "review",
            "feedback",
            "rating",
            "complaint",
            "praise",
            "restaurant review",
            "отзыв",
            "отзывы",
            "рейтинг",
            "жалоба",
            "жалобы",
            "похвала",
            "2гис",
            "2gis",
            "яндекс карты",
            "yandex maps",
        ]
        if any(token in lowered for token in review_keywords):
            tools.append("review_tool")

        if any(token in lowered for token in ["mail", "email", "gmail", "inbox", "letter", "yandex mail", "почта", "письмо", "письма", "ящик"]):
            tools.append("email_tool")
        if any(token in lowered for token in ["calendar", "meeting", "call", "deadline", "schedule", "event", "календарь", "встреча", "созвон", "срок", "расписание", "событие"]):
            tools.append("calendar_tool")
        if any(token in lowered for token in ["revenue", "erp", "crm", "dashboard", "iiko", "1c", "website", "web system", "сайт", "кабинет", "внешняя система", "2гис", "2gis", "яндекс карты", "yandex maps", "точка", "точки"]):
            tools.append("browser_tool")

        if not tools:
            tools.append("orchestrator")

        deduped_tools = list(dict.fromkeys(tools))
        return OrchestratorPlan(selected_tools=deduped_tools, reasoning="Fallback routing by keywords.")

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
            if browser_result.get("status") == "completed" and browser_result.get("data"):
                parts.append(f"Внешняя система:\n{browser_result.get('data')}")
            elif browser_result.get("connected_systems", 0) > 0:
                parts.append(
                    f"Внешние системы: подключено {browser_result.get('connected_systems', 0)}. "
                    "Browser Tool не смог завершить сценарий автоматически, нужен повторный запуск или уточнение запроса."
                )
            else:
                parts.append("Внешние системы пока не подключены. Используйте /connect.")

        review_result = tool_results.get("review_tool")
        if review_result:
            if review_result.get("status") == "ok":
                parts.append(review_result.get("report_text", "Отчёт по отзывам собран."))
            else:
                parts.append(
                    "Отчёт по отзывам сейчас недоступен. "
                    f"Причина: {review_result.get('message', 'источник не настроен')}"
                )

        if not parts:
            parts.append("Пока не удалось собрать полезные данные по этому запросу. Нужен более конкретный источник или уточнение задачи.")

        return "\n\n".join(parts)


orchestrator = DataAgentOrchestrator()
