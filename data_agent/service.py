from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from db.database import get_db_session
from db.models import DataAgentMonitorConfig, DataAgentProfile, DataAgentRequestLog, DataAgentSession, DataAgentSystem, User
from email_integration.encryption import encrypt_password

from .agent_runtime import agent_runtime
from .debugging import build_debug_artifacts, derive_response_status
from .models import (
    ConnectedSystem,
    DataAgentChatRequest,
    DataAgentChatResponse,
    DataAgentDebugResponse,
    MonitorConfigItem,
    MonitorDeleteResponse,
    SystemConnectRequest,
    SystemConnectResponse,
)
from .monitoring import (
    build_monitor_saved_note,
    default_monitor_window_hours,
    scenario_to_monitor_type,
    service_monitor_window_to_user_hours,
    user_monitor_window_to_service_hours,
)
from .scenario_engine import scenario_engine

logger = logging.getLogger(__name__)


class DataAgentService:
    @staticmethod
    def _merge_answer_with_monitor_note(answer: str, monitor_note: str | None) -> str:
        normalized_answer = (answer or "").strip()
        normalized_note = (monitor_note or "").strip()
        if not normalized_note:
            return normalized_answer or "Не удалось сформировать ответ."
        if not normalized_answer:
            return normalized_note
        return f"{normalized_note}\n\nТекущий срез по запросу:\n{normalized_answer}"

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
            elif "rocketdata" in domain:
                system_name = "rocketdata"
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

    def list_monitors(self, user_id: int) -> List[MonitorConfigItem]:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return []
            items = (
                db.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.user_id == user.id,
                    DataAgentMonitorConfig.is_active == True,
                )
                .order_by(
                    DataAgentMonitorConfig.monitor_type.asc(),
                    DataAgentMonitorConfig.point_name.asc(),
                )
                .all()
            )
            return [
                MonitorConfigItem(
                    id=item.id,
                    monitor_type=item.monitor_type,
                    point_name=item.point_name,
                    check_interval_minutes=item.check_interval_minutes,
                    is_active=item.is_active,
                    last_status=item.last_status,
                )
                for item in items
            ]
        finally:
            db.close()

    def delete_monitor(self, user_id: int, monitor_id: int) -> MonitorDeleteResponse:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return MonitorDeleteResponse(success=False, error="user_not_found")

            item = (
                db.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.user_id == user.id,
                    DataAgentMonitorConfig.id == monitor_id,
                    DataAgentMonitorConfig.is_active == True,
                )
                .first()
            )
            if not item:
                return MonitorDeleteResponse(success=False, error="monitor_not_found")

            item.is_active = False
            db.commit()
            return MonitorDeleteResponse(success=True, deleted_id=monitor_id)
        except Exception as exc:
            db.rollback()
            return MonitorDeleteResponse(success=False, error=str(exc))
        finally:
            db.close()

    def get_debug_snapshot(self, user_id: int) -> DataAgentDebugResponse:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return DataAgentDebugResponse(found=False)

            session = db.query(DataAgentSession).filter(DataAgentSession.user_id == user.id).first()
            fallback_log = (
                db.query(DataAgentRequestLog)
                .filter(DataAgentRequestLog.user_id == user.id)
                .order_by(DataAgentRequestLog.created_at.desc(), DataAgentRequestLog.id.desc())
                .first()
            )

            if session and session.last_trace_id and (
                not fallback_log or fallback_log.trace_id == session.last_trace_id
            ):
                return DataAgentDebugResponse(
                    found=True,
                    trace_id=session.last_trace_id,
                    scenario=session.active_scenario,
                    status=session.status or "unknown",
                    summary=session.last_debug_summary,
                    selected_tools=list(session.last_selected_tools or []),
                    user_message=session.last_user_message,
                    answer=session.last_answer,
                    details=session.last_debug_payload or {},
                )

            if not fallback_log:
                return DataAgentDebugResponse(found=False)

            selected_tools = list(fallback_log.selected_tools or [])
            fallback_status = "completed" if fallback_log.success else "failed"
            summary_lines = [
                f"Trace: {fallback_log.trace_id}",
                "Сценарий: unknown",
                f"Статус: {fallback_status}",
            ]
            if selected_tools:
                summary_lines.append(f"Инструменты: {', '.join(str(item) for item in selected_tools)}")
            if fallback_log.error_message:
                summary_lines.append(f"Причина: {fallback_log.error_message}")

            return DataAgentDebugResponse(
                found=True,
                trace_id=fallback_log.trace_id,
                scenario="unknown",
                status=fallback_status,
                summary="\n".join(summary_lines),
                selected_tools=selected_tools,
                user_message=fallback_log.user_message,
                answer=None,
                details={
                    "source": "request_log_fallback",
                    "duration_ms": fallback_log.duration_ms,
                    "success": fallback_log.success,
                },
            )
        finally:
            db.close()

    def _upsert_monitor(
        self,
        *,
        user_id: int,
        scenario: str,
        point_name: str,
        interval_minutes: int,
        start_hour: int | None = None,
        end_hour: int | None = None,
    ) -> str | None:
        monitor_type = scenario_to_monitor_type(scenario)
        if scenario == "reviews_report" and interval_minutes:
            monitor_type = "reviews"
            point_name = point_name or "все точки"

        if not monitor_type or not point_name or not interval_minutes:
            return None

        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return None

            existing = (
                db.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.user_id == user.id,
                    DataAgentMonitorConfig.monitor_type == monitor_type,
                    DataAgentMonitorConfig.point_name == point_name,
                )
                .first()
            )

            if start_hour is not None and end_hour is not None:
                user_window = (start_hour, end_hour)
            elif existing and existing.active_from_hour is not None and existing.active_to_hour is not None:
                user_window = service_monitor_window_to_user_hours(
                    existing.active_from_hour,
                    existing.active_to_hour,
                )
            else:
                user_window = default_monitor_window_hours()

            service_start_hour, service_end_hour = user_monitor_window_to_service_hours(*user_window)
            if not existing:
                existing = DataAgentMonitorConfig(
                    user_id=user.id,
                    system_name="italian_pizza",
                    monitor_type=monitor_type,
                    point_name=point_name,
                    check_interval_minutes=interval_minutes,
                    is_active=True,
                    active_from_hour=service_start_hour,
                    active_to_hour=service_end_hour,
                )
                db.add(existing)
            else:
                existing.check_interval_minutes = interval_minutes
                existing.is_active = True
                if start_hour is not None and end_hour is not None:
                    existing.active_from_hour = service_start_hour
                    existing.active_to_hour = service_end_hour
                elif existing.active_from_hour is None or existing.active_to_hour is None:
                    existing.active_from_hour = service_start_hour
                    existing.active_to_hour = service_end_hour

            profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
            chat_title = profile.default_report_chat_title if profile else None
            db.commit()
            return build_monitor_saved_note(
                monitor_type=monitor_type,
                point_name=point_name,
                interval_minutes=interval_minutes,
                chat_title=chat_title,
                start_hour=user_window[0],
                end_hour=user_window[1],
            )
        except Exception:
            db.rollback()
            logger.exception("Failed to upsert monitor")
            return None
        finally:
            db.close()

    async def chat(self, payload: DataAgentChatRequest) -> DataAgentChatResponse:
        trace_id = str(uuid4())
        started_at = time.perf_counter()
        selected_tools: List[str] = []
        success = True
        error_message: Optional[str] = None
        debug_summary: Optional[str] = None
        normalized_message = self._normalize_user_message(payload.message)

        try:
            systems = self.list_systems(payload.user_id)
            logger.info("DataAgent chat trace=%s user_id=%s systems=%s message=%s", trace_id, payload.user_id, len(systems), normalized_message[:300])
            routing_started = time.perf_counter()
            decision = await agent_runtime.decide(payload.user_id, normalized_message, systems_count=len(systems))
            routing_elapsed = time.perf_counter() - routing_started
            selected_tools = decision.selected_tools
            logger.info(
                "DataAgent plan trace=%s scenario=%s selected_tools=%s slots=%s reasoning=%s routing_elapsed=%.2fs",
                trace_id,
                decision.scenario,
                selected_tools,
                decision.slots,
                decision.reasoning,
                routing_elapsed,
            )

            if decision.missing_slots:
                answer = agent_runtime.build_missing_slots_answer(decision)
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="awaiting_user_input",
                    selected_tools=selected_tools,
                    tool_results={},
                    error_message=f"missing_slots: {', '.join(decision.missing_slots)}",
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="awaiting_user_input",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="awaiting_user_input",
                    debug_summary=debug_summary,
                )

            execution_started = time.perf_counter()
            execution = await scenario_engine.execute(
                scenario=decision.scenario,
                user_id=payload.user_id,
                user_message=normalized_message,
                slots=decision.slots,
                systems=systems,
            )
            execution_elapsed = time.perf_counter() - execution_started
            selected_tools = execution.selected_tools
            logger.info(
                "DataAgent tool_results trace=%s keys=%s execution_elapsed=%.2fs total_elapsed=%.2fs",
                trace_id,
                list(execution.tool_results.keys()),
                execution_elapsed,
                time.perf_counter() - started_at,
            )
            answer = execution.answer or "Не удалось сформировать ответ."
            response_status = derive_response_status(execution.tool_results)
            debug_payload, debug_summary = build_debug_artifacts(
                trace_id=trace_id,
                scenario=decision.scenario,
                status=response_status,
                selected_tools=selected_tools,
                tool_results=execution.tool_results,
            )
            success = response_status != "failed"
            interval_minutes = decision.slots.get("monitor_interval_minutes")
            point_name = decision.slots.get("point_name")
            start_hour = decision.slots.get("monitor_start_hour")
            end_hour = decision.slots.get("monitor_end_hour")
            if isinstance(interval_minutes, int) and interval_minutes > 0 and point_name:
                monitor_note = self._upsert_monitor(
                    user_id=payload.user_id,
                    scenario=decision.scenario,
                    point_name=point_name,
                    interval_minutes=interval_minutes,
                    start_hour=start_hour,
                    end_hour=end_hour,
                )
                if monitor_note:
                    answer = self._merge_answer_with_monitor_note(answer, monitor_note)
            agent_runtime.save_session(
                payload.user_id,
                decision,
                user_message=normalized_message,
                answer=answer,
                status=response_status,
                trace_id=trace_id,
                debug_summary=debug_summary,
                debug_payload=debug_payload,
            )
            return DataAgentChatResponse(
                ok=response_status != "failed",
                answer=answer,
                selected_tools=selected_tools,
                trace_id=trace_id,
                scenario=decision.scenario,
                status=response_status,
                debug_summary=debug_summary,
            )
        except Exception as exc:
            success = False
            error_message = str(exc)
            logger.exception("DataAgent chat failed trace=%s", trace_id)
            fallback_decision = agent_runtime.decide_fast(payload.user_id, normalized_message, systems_count=0)
            fallback_answer = f"DataAgent не смог обработать запрос: {exc}"
            debug_payload, debug_summary = build_debug_artifacts(
                trace_id=trace_id,
                scenario=fallback_decision.scenario,
                status="failed",
                selected_tools=selected_tools,
                tool_results={},
                error_message=error_message,
            )
            agent_runtime.save_session(
                payload.user_id,
                fallback_decision,
                user_message=normalized_message,
                answer=fallback_answer,
                status="failed",
                trace_id=trace_id,
                debug_summary=debug_summary,
                debug_payload=debug_payload,
            )
            return DataAgentChatResponse(
                ok=False,
                answer=fallback_answer,
                selected_tools=selected_tools,
                trace_id=trace_id,
                scenario=fallback_decision.scenario,
                status="failed",
                debug_summary=debug_summary,
            )
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
