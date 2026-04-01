from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List
from urllib.parse import quote
from uuid import uuid4

from db.database import get_db_session
from db.models import DataAgentRequestLog, DataAgentSystem, User
from email_integration.encryption import encrypt_password

from .browser_agent import browser_agent
from .blanks_tool import blanks_tool
from .internal_api_client import internal_api_client
from .italian_pizza import ITALIAN_PIZZA_PORTAL_URL, resolve_italian_pizza_point
from .models import ConnectedSystem, DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse
from .orchestrator import orchestrator
from .review_report import review_report_service
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)


class DataAgentService:
    """DataAgent service with persistent systems, internal tools, and Browser Agent MVP."""

    def _normalize_user_message(self, message: str) -> str:
        raw = (message or "").strip()
        if not raw:
            return ""

        half = len(raw) // 2
        if len(raw) > 40 and len(raw) % 2 == 0 and raw[:half].strip() == raw[half:].strip():
            return raw[:half].strip()

        normalized = raw.replace("\r\n", "\n").strip()
        while "\n\n\n" in normalized:
            normalized = normalized.replace("\n\n\n", "\n\n")
        return normalized

    def _looks_like_point_or_followup(self, message: str) -> bool:
        lowered = (message or "").lower()
        if resolve_italian_pizza_point(lowered):
            return True
        followup_markers = [
            "по ленина",
            "по адресу",
            "вот этот адрес",
            "эта точка",
            "по этой системе",
            "по всем своим точкам",
            "раз в час",
            "раз в три часа",
            "каждый час",
            "каждые три часа",
        ]
        return any(marker in lowered for marker in followup_markers)

    def _infer_followup_tools(self, user_id: int, message: str) -> List[str]:
        if not self._looks_like_point_or_followup(message):
            return []

        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return []

            recent_logs = (
                db.query(DataAgentRequestLog)
                .filter(DataAgentRequestLog.user_id == user.id)
                .order_by(DataAgentRequestLog.created_at.desc())
                .limit(5)
                .all()
            )

            for item in recent_logs:
                tools = item.selected_tools or []
                filtered = [tool for tool in tools if tool in {"stoplist_tool", "blanks_tool", "review_tool"}]
                if filtered:
                    return filtered
            return []
        finally:
            db.close()

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
            elif "italianpizza" in domain or "tochka.italianpizza" in domain:
                system_name = "italian_pizza"
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
            normalized_message = self._normalize_user_message(payload.message)
            systems = self.list_systems(payload.user_id)
            logger.info("DataAgent chat trace=%s user_id=%s systems=%s message=%s", trace_id, payload.user_id, len(systems), normalized_message[:300])
            plan = await orchestrator.plan(normalized_message, systems_count=len(systems))
            if plan.selected_tools == ["orchestrator"]:
                inferred_tools = self._infer_followup_tools(payload.user_id, normalized_message)
                if inferred_tools:
                    plan.selected_tools = inferred_tools
                    plan.reasoning = f"Контекстный follow-up routing: {', '.join(inferred_tools)}"
            selected_tools = plan.selected_tools
            logger.info("DataAgent plan trace=%s selected_tools=%s reasoning=%s", trace_id, selected_tools, plan.reasoning)
            tool_results = await self._collect_tool_results(payload.user_id, normalized_message, selected_tools, systems)
            logger.info("DataAgent tool_results trace=%s keys=%s", trace_id, list(tool_results.keys()))
            answer = await orchestrator.synthesize(normalized_message, tool_results)
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
            tool_results["review_tool"] = await self._run_review_tool(user_message, systems, user_id)

        if "stoplist_tool" in selected_tools:
            tool_results["stoplist_tool"] = await self._run_stoplist_tool(user_message, systems, user_id)

        if "blanks_tool" in selected_tools:
            tool_results["blanks_tool"] = await self._run_blanks_tool(user_message, systems, user_id)

        if "orchestrator" in selected_tools and not tool_results:
            tool_results["orchestrator"] = {
                "status": "no_tool_selected",
                "message": "Для ответа не потребовались внутренние инструменты.",
            }

        return tool_results

    def _extract_urls(self, text: str) -> List[str]:
        import re

        return re.findall(r"https?://[^\s)]+", text or "")

    def _extract_review_targets(self, text: str) -> List[str]:
        import re

        raw = (text or "").strip()
        urls = self._extract_urls(raw)
        if urls:
            return urls

        point_name = self._resolve_point_name(raw)
        explicit_patterns = [
            r"по адресу\s+(.+?)(?:$|\n|;)",
            r"адрес(?:а)?\s*[:\-]\s*(.+?)(?:$|\n|;)",
            r"точк[ае]\s*[:\-]\s*(.+?)(?:$|\n|;)",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE | re.DOTALL)
            if match:
                candidate = match.group(1).strip(" \n\t.;,")
                if point_name and "italian pizza" not in candidate.lower():
                    candidate = f"Italian Pizza, {candidate}"
                if candidate and len(candidate) >= 6:
                    return [candidate]

        if point_name and ("по адресу" in raw.lower() or "адрес" in raw.lower()):
            address_match = re.search(r"(ул\.?\s*[^;\n]+|улица\s+[^;\n]+)", raw, flags=re.IGNORECASE)
            if address_match:
                return [f"Italian Pizza, {address_match.group(1).strip(' ,.;')}"]

        separators = re.split(r"[\n;]+", raw)
        targets: List[str] = []
        for item in separators:
            cleaned = item.strip(" -\t")
            if not cleaned:
                continue
            if len(cleaned) < 6:
                continue
            lowered = cleaned.lower()
            if any(token in lowered for token in ["за сегодня", "за сутки", "за неделю", "за последние", "мне нужны отзывы", "собери отзывы", "покажи отзывы"]):
                continue
            cleaned = re.sub(
                r"^(мне нужны|нужны|собери|покажи|посмотри)\s+отзывы\s+(?:за.+?\s+)?(?:по|для)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip(" .,:;-")
            if cleaned:
                targets.append(cleaned)

        if not targets and point_name:
            address_match = re.search(r"(ул\.?\s*[^;\n]+|улица\s+[^;\n]+)", raw, flags=re.IGNORECASE)
            if address_match:
                targets.append(f"Italian Pizza, {address_match.group(1).strip(' ,.;')}")
            else:
                targets.append(point_name)

        return targets[:5]

    def _resolve_point_name(self, user_message: str) -> str | None:
        point = resolve_italian_pizza_point(user_message)
        if point:
            return point.display_name
        return None

    def _extract_period_hint(self, message: str) -> str:
        lowered = (message or "").lower()
        if "последние 3 часа" in lowered or "за три часа" in lowered:
            return "последние 3 часа"
        if "за сутки" in lowered or "последние сутки" in lowered:
            return "последние сутки"
        if "сегодня" in lowered:
            return "сегодня"
        if "раз в час" in lowered or "каждый час" in lowered:
            return "текущий бланк, проверка каждый час"
        return "текущий бланк"

    def _find_italian_pizza_system(self, db, user_id: int) -> DataAgentSystem | None:
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

    def _looks_like_public_reviews_request(self, text: str) -> bool:
        lowered = (text or "").lower()
        review_markers = ["отзыв", "отзывы", "2гис", "2gis", "яндекс карты", "yandex maps", "карты", "точка", "точки"]
        return any(marker in lowered for marker in review_markers)

    async def _run_review_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        logger.info("Review tool invoked user_id=%s message=%s", user_id, user_message[:300])
        if self._looks_like_public_reviews_request(user_message):
            public_result = await self._run_public_reviews_browser(user_message)
            if public_result:
                return public_result

        return await review_report_service.build_report(user_message)

    async def _run_public_reviews_browser(self, user_message: str) -> dict:
        targets = self._extract_review_targets(user_message)
        logger.info("Public reviews resolution message=%s targets=%s", user_message[:300], targets)
        if not targets:
            return {
                "status": "needs_targets",
                "message": "Не удалось выделить точку из запроса. Пришлите адрес точки, название пиццерии или ссылку на карточку 2GIS/Яндекс Карт.",
            }

        lowered = user_message.lower()
        provider = "2gis" if ("2гис" in lowered or "2gis" in lowered) else "yandex_maps"
        results: List[dict] = []

        for target in targets[:5]:
            if target.startswith("http://") or target.startswith("https://"):
                target_url = target
                target_label = target
            else:
                if provider == "2gis":
                    target_url = f"https://2gis.ru/search/{quote(target)}"
                else:
                    target_url = f"https://yandex.ru/maps/?text={quote(target)}"
                target_label = target

            task_text = (
                "Собери краткий отчет по отзывам для этой точки. "
                "Найди свежие отзывы, общую тональность, основные жалобы, основные похвалы "
                "и если возможно укажи среднюю оценку. Ответ верни кратко и по делу.\n\n"
                f"Точка: {target_label}\n"
                f"Исходный запрос пользователя: {user_message}"
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
            return {
                "status": "failed",
                "message": "Не удалось собрать отзывы по переданным точкам.",
                "targets": results,
            }

        report_lines = ["Отчет по отзывам по точкам:"]
        for item in ok_results:
            report_lines.append(f"\nТочка: {item['target']}\n{item['data']}")

        return {
            "status": "ok",
            "source": provider,
            "targets": results,
            "report_text": "\n".join(report_lines).strip(),
        }

    async def _run_stoplist_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        point_name = self._resolve_point_name(user_message)
        logger.info("Stoplist tool invoked user_id=%s point=%s message=%s", user_id, point_name, user_message[:300])
        if not point_name:
            return {
                "status": "needs_point",
                "message": "Не удалось определить точку. Укажите город и адрес пиццерии.",
            }

        db = get_db_session()
        try:
            logger.info("Stoplist tool using public ordering site point=%s", point_name)
            return await stoplist_tool.collect_for_point(
                url="",
                username="",
                encrypted_password="",
                point_name=point_name,
            )
        except Exception as exc:
            logger.error("Stoplist tool failed user_id=%s point=%s error=%s", user_id, point_name, exc, exc_info=True)
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()

    async def _run_blanks_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        point_name = self._resolve_point_name(user_message)
        logger.info("Blanks tool invoked user_id=%s point=%s message=%s", user_id, point_name, user_message[:300])
        if not point_name:
            return {
                "status": "needs_point",
                "message": "Не удалось определить точку. Укажите город и адрес пиццерии.",
            }

        db = get_db_session()
        try:
            system = self._find_italian_pizza_system(db, user_id)
            if not system:
                return {
                    "status": "system_not_connected",
                    "message": "Italian Pizza портал ещё не подключён. Используйте /connect для tochka.italianpizza.ru.",
                }

            period_hint = self._extract_period_hint(user_message)
            logger.info("Blanks tool using system=%s url=%s point=%s period=%s", system.system_name, system.url, point_name, period_hint)
            return await blanks_tool.inspect_point(
                url=system.url or ITALIAN_PIZZA_PORTAL_URL,
                username=system.login,
                encrypted_password=system.encrypted_password,
                point_name=point_name,
                period_hint=period_hint,
            )
        except Exception as exc:
            logger.error("Blanks tool failed user_id=%s point=%s error=%s", user_id, point_name, exc, exc_info=True)
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()

    async def _run_browser_tool(self, user_message: str, systems: List[ConnectedSystem], user_id: int) -> dict:
        logger.info("Browser tool invoked user_id=%s systems=%s message=%s", user_id, len(systems), user_message[:300])
        if not systems:
            if self._looks_like_public_reviews_request(user_message):
                public_result = await self._run_public_reviews_browser(user_message)
                return {
                    "connected_systems": 0,
                    "systems": [],
                    "status": public_result.get("status", "completed"),
                    "data": public_result.get("report_text") or public_result.get("message"),
                    "details": public_result,
                }
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
                logger.info("Browser tool using connected system system=%s url=%s", system.system_name, system.url)
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

