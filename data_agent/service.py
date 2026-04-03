from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote
from uuid import uuid4

from db.database import get_db_session
from db.models import DataAgentRequestLog, DataAgentSystem, User
from email_integration.encryption import encrypt_password

from .agent_runtime import agent_runtime
from .blanks_tool import blanks_tool
from .browser_agent import browser_agent
from .internal_api_client import internal_api_client
from .italian_pizza import ITALIAN_PIZZA_PORTAL_URL
from .models import ConnectedSystem, DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse
from .orchestrator import orchestrator
from .review_report import review_report_service
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)


class DataAgentService:
    def health(self) -> dict:
        return {"status": "ok", "service": "data_agent", "mode": "session_scenario_runtime"}

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
            elif "1c" in domain or "1с" in domain:
                system_name = "1C"
            elif "crm" in domain:
                system_name = "CRM"
            else:
                system_name = "web-system"
            existing = db.query(DataAgentSystem).filter(DataAgentSystem.user_id == user.id, DataAgentSystem.url == str(payload.url), DataAgentSystem.login == payload.username).first()
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
            system = DataAgentSystem(user_id=user.id, system_name=system_name, url=str(payload.url), login=payload.username, encrypted_password=encrypted_password, secret_storage="fernet_local", is_active=True, metadata_json={"phase": 2}, last_connected_at=datetime.utcnow())
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
            systems = db.query(DataAgentSystem).filter(DataAgentSystem.user_id == user.id).order_by(DataAgentSystem.created_at.desc()).all()
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
            tool_results = await self._collect_tool_results(payload.user_id, normalized_message, selected_tools, systems, runtime_slots=decision.slots)
            logger.info("DataAgent tool_results trace=%s keys=%s", trace_id, list(tool_results.keys()))
            answer = await orchestrator.synthesize(normalized_message, tool_results)
            agent_runtime.save_session(payload.user_id, decision, user_message=normalized_message, answer=answer, status="completed")
            return DataAgentChatResponse(answer=answer, selected_tools=selected_tools, trace_id=trace_id)
        except Exception as exc:
            success = False
            error_message = str(exc)
            logger.exception("DataAgent chat failed trace=%s", trace_id)
            fallback_decision = await agent_runtime.decide(payload.user_id, normalized_message, systems_count=0)
            agent_runtime.save_session(payload.user_id, fallback_decision, user_message=normalized_message, answer=f"DataAgent не смог обработать запрос: {exc}", status="failed")
            return DataAgentChatResponse(ok=False, answer=f"DataAgent не смог обработать запрос: {exc}", selected_tools=selected_tools, trace_id=trace_id)
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
            log_item = DataAgentRequestLog(user_id=user.id, trace_id=trace_id, user_message=self._normalize_user_message(payload.message), selected_tools=selected_tools, success=success, duration_ms=duration_ms, error_message=error_message)
            db.add(log_item)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _to_connected_system(self, system: DataAgentSystem) -> ConnectedSystem:
        return ConnectedSystem(system_id=str(system.id), user_id=system.user.telegram_id if system.user else system.user_id, system_name=system.system_name, url=system.url, login=system.login, is_active=system.is_active, created_at=system.created_at)

    async def _collect_tool_results(self, user_id: int, user_message: str, selected_tools: List[str], systems: List[ConnectedSystem], runtime_slots: Optional[dict] = None) -> dict:
        tool_results: dict = {}
        runtime_slots = runtime_slots or {}
        if "email_tool" in selected_tools:
            tool_results["email_tool"] = await internal_api_client.get_email_summary(user_id, days=7)
        if "calendar_tool" in selected_tools:
            tool_results["calendar_tool"] = await internal_api_client.get_calendar_events(user_id, days=7)
        if "browser_tool" in selected_tools:
            tool_results["browser_tool"] = await self._run_browser_tool(user_message, systems, user_id)
        if "review_tool" in selected_tools:
            tool_results["review_tool"] = await self._run_review_tool(user_message, systems, user_id, point_name=runtime_slots.get("point_name"))
        if "stoplist_tool" in selected_tools:
            tool_results["stoplist_tool"] = await self._run_stoplist_tool(user_message, systems, user_id, point_name=runtime_slots.get("point_name"))
        if "blanks_tool" in selected_tools:
            tool_results["blanks_tool"] = await self._run_blanks_tool(user_message, systems, user_id, point_name=runtime_slots.get("point_name"), period_hint=runtime_slots.get("period_hint"))
        if "orchestrator" in selected_tools and not tool_results:
            tool_results["orchestrator"] = {"status": "no_tool_selected", "message": "Для ответа не потребовались внутренние инструменты."}
        return tool_results

    def _extract_urls(self, text: str) -> List[str]:
        import re
        return re.findall(r"https?://[^\s)]+", text or "")

    def _extract_review_targets(self, text: str, point_name: Optional[str] = None) -> List[str]:
        raw = (text or "").strip()
        urls = self._extract_urls(raw)
        if urls:
            return urls
        if point_name:
            return [point_name]
        return []

    def _find_italian_pizza_system(self, db, user_id: int) -> DataAgentSystem | None:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            return None
        return db.query(DataAgentSystem).filter(DataAgentSystem.user_id == user.id, DataAgentSystem.is_active == True, (DataAgentSystem.system_name == "italian_pizza") | (DataAgentSystem.url.contains("italianpizza"))).order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc()).first()

    async def _run_review_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int, point_name: Optional[str] = None) -> dict:
        logger.info("Review tool invoked user_id=%s point=%s message=%s", user_id, point_name, user_message[:300])
        targets = self._extract_review_targets(user_message, point_name=point_name)
        if targets:
            return await self._run_public_reviews_browser(user_message, targets=targets)
        return await review_report_service.build_report(user_message)

    async def _run_public_reviews_browser(self, user_message: str, targets: Optional[List[str]] = None) -> dict:
        targets = targets or []
        logger.info("Public reviews resolution message=%s targets=%s", user_message[:300], targets)
        if not targets:
            return {"status": "needs_targets", "message": "Не удалось выделить точку из запроса. Пришлите адрес точки, название пиццерии или ссылку на карточку 2GIS/Яндекс Карт."}
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
                data = await browser_agent.extract_data(url=target_url, username=None, encrypted_password=None, user_task=task_text, progress_callback=None)
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

    async def _run_stoplist_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int, point_name: Optional[str] = None) -> dict:
        logger.info("Stoplist tool invoked user_id=%s point=%s message=%s", user_id, point_name, user_message[:300])
        if not point_name:
            return {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}
        try:
            logger.info("Stoplist tool using public ordering site point=%s", point_name)
            return await stoplist_tool.collect_for_point(url="", username="", encrypted_password="", point_name=point_name)
        except Exception as exc:
            logger.error("Stoplist tool failed user_id=%s point=%s error=%s", user_id, point_name, exc, exc_info=True)
            return {"status": "failed", "error": str(exc)}

    async def _run_blanks_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int, point_name: Optional[str] = None, period_hint: Optional[str] = None) -> dict:
        logger.info("Blanks tool invoked user_id=%s point=%s message=%s", user_id, point_name, user_message[:300])
        if not point_name:
            return {"status": "needs_point", "message": "Не удалось определить точку. Укажите город и адрес пиццерии."}
        db = get_db_session()
        try:
            system = self._find_italian_pizza_system(db, user_id)
            if not system:
                return {"status": "system_not_connected", "message": "Italian Pizza портал ещё не подключён. Используйте /connect для tochka.italianpizza.ru."}
            effective_period = period_hint or "текущий бланк"
            logger.info("Blanks tool using system=%s url=%s point=%s period=%s", system.system_name, system.url, point_name, effective_period)
            return await blanks_tool.inspect_point(url=system.url or ITALIAN_PIZZA_PORTAL_URL, username=system.login, encrypted_password=system.encrypted_password, point_name=point_name, period_hint=effective_period)
        except Exception as exc:
            logger.error("Blanks tool failed user_id=%s point=%s error=%s", user_id, point_name, exc, exc_info=True)
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()

    async def _run_browser_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        logger.info("Browser tool invoked user_id=%s systems=%s message=%s", user_id, len(systems), user_message[:300])
        if not systems:
            return {"connected_systems": 0, "systems": [], "status": "no_systems_connected"}
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return {"connected_systems": 0, "systems": [], "status": "user_not_found"}
            system = db.query(DataAgentSystem).filter(DataAgentSystem.user_id == user.id, DataAgentSystem.is_active == True).order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc()).first()
            if not system:
                return {"connected_systems": 0, "systems": [], "status": "system_not_found"}
            try:
                logger.info("Browser tool using connected system system=%s url=%s", system.system_name, system.url)
                result = await browser_agent.extract_data(url=system.url, username=system.login, encrypted_password=system.encrypted_password, user_task=user_message, progress_callback=None)
                return {"connected_systems": len(systems), "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}], "status": "completed", "data": result}
            except Exception as exc:
                logger.warning("Browser tool execution fallback used: %s", exc)
                return {"connected_systems": len(systems), "systems": [{"system_name": system.system_name, "url": system.url, "login": system.login}], "status": "failed", "error": str(exc)}
        finally:
            db.close()


service = DataAgentService()
