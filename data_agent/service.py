from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List
from uuid import uuid4

from db.database import get_db_session
from db.models import DataAgentRequestLog, DataAgentSystem, User
from email_integration.encryption import encrypt_password

from .browser_agent import browser_agent
from .internal_api_client import internal_api_client
from .models import ConnectedSystem, DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse
from .orchestrator import orchestrator
from .review_report import review_report_service

logger = logging.getLogger(__name__)


class DataAgentService:
    """DataAgent service with persistent systems, internal tools, and Browser Agent MVP."""

    def health(self) -> dict:
        return {
            "status": "ok",
            "service": "data_agent",
            "mode": "phase_4_browser_mvp",
        }

    async def connect_system(self, payload: SystemConnectRequest) -> SystemConnectResponse:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == payload.user_id).first()
            if not user:
                user = User(
                    telegram_id=payload.user_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                    is_bot=False,
                )
                db.add(user)
                db.flush()

            domain = payload.url.host.lower()
            if "iiko" in domain:
                system_name = "iiko"
            elif "1c" in domain or "1с" in domain:
                system_name = "1C"
            elif "crm" in domain:
                system_name = "CRM"
            else:
                system_name = "web-system"

            existing = (
                db.query(DataAgentSystem)
                .filter(
                    DataAgentSystem.user_id == user.id,
                    DataAgentSystem.url == str(payload.url),
                    DataAgentSystem.login == payload.username,
                )
                .first()
            )

            encrypted_password = encrypt_password(payload.password)
            if existing:
                existing.system_name = system_name
                existing.encrypted_password = encrypted_password
                existing.is_active = True
                existing.last_connected_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return SystemConnectResponse(success=True, system=self._to_connected_system(existing))

            system = DataAgentSystem(
                user_id=user.id,
                system_name=system_name,
                url=str(payload.url),
                login=payload.username,
                encrypted_password=encrypted_password,
                secret_storage="fernet_local",
                is_active=True,
                metadata_json={"phase": 2},
                last_connected_at=datetime.utcnow(),
            )
            db.add(system)
            db.commit()
            db.refresh(system)
            return SystemConnectResponse(success=True, system=self._to_connected_system(system))
        except Exception as exc:
            db.rollback()
            return SystemConnectResponse(success=False, error=str(exc))
        finally:
            db.close()

    def list_systems(self, user_id: int) -> List[ConnectedSystem]:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return []

            systems = (
                db.query(DataAgentSystem)
                .filter(DataAgentSystem.user_id == user.id)
                .order_by(DataAgentSystem.created_at.desc())
                .all()
            )
            return [self._to_connected_system(item) for item in systems]
        finally:
            db.close()

    async def chat(self, payload: DataAgentChatRequest) -> DataAgentChatResponse:
        trace_id = str(uuid4())
        started_at = time.perf_counter()
        selected_tools: List[str] = []
        success = True
        error_message = None

        try:
            systems = self.list_systems(payload.user_id)
            plan = await orchestrator.plan(payload.message, systems_count=len(systems))
            selected_tools = plan.selected_tools
            tool_results = await self._collect_tool_results(payload.user_id, payload.message, selected_tools, systems)
            answer = await orchestrator.synthesize(payload.message, tool_results)
            return DataAgentChatResponse(
                answer=answer,
                selected_tools=selected_tools,
                trace_id=trace_id,
            )
        except Exception as exc:
            success = False
            error_message = str(exc)
            return DataAgentChatResponse(
                ok=False,
                answer=f"DataAgent не смог обработать запрос: {exc}",
                selected_tools=selected_tools,
                trace_id=trace_id,
            )
        finally:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._log_request(
                payload=payload,
                trace_id=trace_id,
                selected_tools=selected_tools,
                success=success,
                duration_ms=duration_ms,
                error_message=error_message,
            )

    def _log_request(
        self,
        payload: DataAgentChatRequest,
        trace_id: str,
        selected_tools: List[str],
        success: bool,
        duration_ms: int,
        error_message: str | None,
    ) -> None:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == payload.user_id).first()
            if not user:
                user = User(
                    telegram_id=payload.user_id,
                    username=payload.username,
                    first_name=payload.first_name,
                    last_name=None,
                    is_bot=False,
                )
                db.add(user)
                db.flush()

            log_item = DataAgentRequestLog(
                user_id=user.id,
                trace_id=trace_id,
                user_message=payload.message,
                selected_tools=selected_tools,
                success=success,
                duration_ms=duration_ms,
                error_message=error_message,
            )
            db.add(log_item)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _to_connected_system(self, system: DataAgentSystem) -> ConnectedSystem:
        return ConnectedSystem(
            system_id=str(system.id),
            user_id=system.user.telegram_id if system.user else system.user_id,
            system_name=system.system_name,
            url=system.url,
            login=system.login,
            is_active=system.is_active,
            created_at=system.created_at,
        )

    async def _collect_tool_results(
        self,
        user_id: int,
        user_message: str,
        selected_tools: List[str],
        systems: List[ConnectedSystem],
    ) -> dict:
        tool_results: dict = {}

        if "email_tool" in selected_tools:
            tool_results["email_tool"] = await internal_api_client.get_email_summary(user_id, days=7)

        if "calendar_tool" in selected_tools:
            tool_results["calendar_tool"] = await internal_api_client.get_calendar_events(user_id, days=7)

        if "browser_tool" in selected_tools:
            tool_results["browser_tool"] = await self._run_browser_tool(user_message, systems, user_id)

        if "review_tool" in selected_tools:
            tool_results["review_tool"] = await review_report_service.build_report(user_message)

        if "orchestrator" in selected_tools and not tool_results:
            tool_results["orchestrator"] = {
                "status": "no_tool_selected",
                "message": "Для ответа не потребовались внутренние инструменты.",
            }

        return tool_results

    async def _run_browser_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        if not systems:
            return {
                "connected_systems": 0,
                "systems": [],
                "status": "no_systems_connected",
            }

        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return {"connected_systems": 0, "systems": [], "status": "user_not_found"}

            system = (
                db.query(DataAgentSystem)
                .filter(DataAgentSystem.user_id == user.id, DataAgentSystem.is_active == True)
                .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
                .first()
            )
            if not system:
                return {"connected_systems": 0, "systems": [], "status": "system_not_found"}

            try:
                result = await browser_agent.extract_data(
                    url=system.url,
                    username=system.login,
                    encrypted_password=system.encrypted_password,
                    user_task=user_message,
                    progress_callback=None,
                )
                return {
                    "connected_systems": len(systems),
                    "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}],
                    "status": "completed",
                    "data": result,
                }
            except Exception as exc:
                logger.warning("Browser tool execution fallback used: %s", exc)
                return {
                    "connected_systems": len(systems),
                    "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}],
                    "status": "failed",
                    "error": str(exc),
                }
        finally:
            db.close()


service = DataAgentService()
