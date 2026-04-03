from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from db.database import get_db_session
from db.models import DataAgentRequestLog, DataAgentSystem, User
from email_integration.encryption import encrypt_password

from .agent_runtime import agent_runtime
from .models import ConnectedSystem, DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse
from .scenario_engine import scenario_engine

logger = logging.getLogger(__name__)


class DataAgentService:
    def health(self) -> dict:
        return {"status": "ok", "service": "data_agent", "mode": "scenario_engine_v2"}

    def _normalize_user_message(self, message: str) -> str:
        raw = (message or "").strip()
        if not raw:
            return ""
        normalized = raw.replace("\r\n", "\n").strip()
        while "\n\n\n" in normalized:
            normalized = normalized.replace("\n\n\n", "\n\n")
        return normalized

    async def connect_system(self, payload: SystemConnectRequest) -> SystemConnectResponse:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == payload.user_id).first()
            if not user:
                user = User(telegram_id=payload.user_id, username=None, first_name=None, last_name=None, is_bot=False)
                db.add(user)
                db.flush()

            domain = payload.url.host.lower()
            if "iiko" in domain:
                system_name = "iiko"
            elif "italianpizza" in domain or "tochka.italianpizza" in domain:
                system_name = "italian_pizza"
            elif "1c" in domain or "1С" in domain:
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
        error_message: Optional[str] = None
        normalized_message = self._normalize_user_message(payload.message)

        try:
            systems = self.list_systems(payload.user_id)
            logger.info("DataAgent chat trace=%s user_id=%s systems=%s message=%s", trace_id, payload.user_id, len(systems), normalized_message[:300])
            decision = await agent_runtime.decide(payload.user_id, normalized_message, systems_count=len(systems))
            selected_tools = decision.selected_tools
            logger.info("DataAgent plan trace=%s scenario=%s selected_tools=%s slots=%s reasoning=%s", trace_id, decision.scenario, selected_tools, decision.slots, decision.reasoning)

            if decision.missing_slots:
                answer = agent_runtime.build_missing_slots_answer(decision)
                agent_runtime.save_session(payload.user_id, decision, user_message=normalized_message, answer=answer, status="awaiting_user_input")
                return DataAgentChatResponse(answer=answer, selected_tools=selected_tools, trace_id=trace_id)

            execution = await scenario_engine.execute(
                scenario=decision.scenario,
                user_id=payload.user_id,
                user_message=normalized_message,
                slots=decision.slots,
                systems=systems,
            )
            selected_tools = execution.selected_tools
            logger.info("DataAgent tool_results trace=%s keys=%s", trace_id, list(execution.tool_results.keys()))
            answer = execution.answer or "Не удалось сформировать ответ."
            agent_runtime.save_session(payload.user_id, decision, user_message=normalized_message, answer=answer, status="completed")
            return DataAgentChatResponse(answer=answer, selected_tools=selected_tools, trace_id=trace_id)
        except Exception as exc:
            success = False
            error_message = str(exc)
            logger.exception("DataAgent chat failed trace=%s", trace_id)
            fallback_decision = await agent_runtime.decide(payload.user_id, normalized_message, systems_count=0)
            fallback_answer = f"DataAgent не смог обработать запрос: {exc}"
            agent_runtime.save_session(payload.user_id, fallback_decision, user_message=normalized_message, answer=fallback_answer, status="failed")
            return DataAgentChatResponse(ok=False, answer=fallback_answer, selected_tools=selected_tools, trace_id=trace_id)
        finally:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._log_request(payload=payload, trace_id=trace_id, selected_tools=selected_tools, success=success, duration_ms=duration_ms, error_message=error_message)

    def _log_request(self, payload: DataAgentChatRequest, trace_id: str, selected_tools: List[str], success: bool, duration_ms: int, error_message: str | None) -> None:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == payload.user_id).first()
            if not user:
                user = User(telegram_id=payload.user_id, username=payload.username, first_name=payload.first_name, last_name=None, is_bot=False)
                db.add(user)
                db.flush()
            log_item = DataAgentRequestLog(
                user_id=user.id,
                trace_id=trace_id,
                user_message=self._normalize_user_message(payload.message),
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


service = DataAgentService()
