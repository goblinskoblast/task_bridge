from __future__ import annotations

from datetime import datetime
from typing import Dict, List
from uuid import uuid4

from .models import ConnectedSystem, DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse


class DataAgentService:
    """Phase-1 in-memory skeleton for the separate DataAgent node."""

    def __init__(self) -> None:
        self._systems_by_user: Dict[int, List[ConnectedSystem]] = {}

    def health(self) -> dict:
        return {
            "status": "ok",
            "service": "data_agent",
            "mode": "phase_1_stub",
        }

    def connect_system(self, payload: SystemConnectRequest) -> SystemConnectResponse:
        domain = payload.url.host.lower()
        if "iiko" in domain:
            system_name = "iiko"
        elif "1c" in domain or "1с" in domain:
            system_name = "1C"
        elif "crm" in domain:
            system_name = "CRM"
        else:
            system_name = "web-system"

        system = ConnectedSystem(
            system_id=str(uuid4()),
            user_id=payload.user_id,
            system_name=system_name,
            url=str(payload.url),
            login=payload.username,
            created_at=datetime.utcnow(),
        )
        self._systems_by_user.setdefault(payload.user_id, []).append(system)
        return SystemConnectResponse(success=True, system=system)

    def list_systems(self, user_id: int) -> List[ConnectedSystem]:
        return list(self._systems_by_user.get(user_id, []))

    def chat(self, payload: DataAgentChatRequest) -> DataAgentChatResponse:
        message = payload.message.lower()
        tools: List[str] = []
        if any(token in message for token in ["почт", "письм", "email", "gmail", "яндекс"]):
            tools.append("email_tool")
        if any(token in message for token in ["календар", "встреч", "созвон", "meeting", "call"]):
            tools.append("calendar_tool")
        if any(token in message for token in ["выручк", "erp", "crm", "отчет", "отчёт", "iiko", "1c", "1с", "система"]):
            tools.append("browser_tool")
        if not tools:
            tools.append("orchestrator")

        systems = self._systems_by_user.get(payload.user_id, [])
        systems_hint = (
            f"Подключено систем: {len(systems)}."
            if systems
            else "Подключённых внешних систем пока нет."
        )

        answer = (
            "DataAgent подключен в режиме каркаса.\n\n"
            f"{systems_hint}\n"
            f"Предварительно выбранные инструменты: {', '.join(tools)}.\n\n"
            "Следующий этап: реальный OpenClaw orchestrator, Browser Tool и сохранение подключений в БД/secret storage."
        )

        return DataAgentChatResponse(
            answer=answer,
            selected_tools=tools,
            trace_id=str(uuid4()),
        )


service = DataAgentService()

