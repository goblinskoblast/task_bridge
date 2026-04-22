from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, List, Optional
from uuid import uuid4

from db.database import get_db_session
from db.models import (
    DataAgentMonitorConfig,
    DataAgentMonitorEvent,
    DataAgentProfile,
    DataAgentRequestLog,
    DataAgentSession,
    DataAgentSystem,
    SavedPoint,
    StopListIncident,
    User,
)
from email_integration.encryption import encrypt_password

from .agent_runtime import AgentDecision, agent_runtime
from .debugging import build_debug_artifacts, derive_response_status
from .models import (
    ConnectedSystem,
    DataAgentChatRequest,
    DataAgentChatResponse,
    DataAgentDebugResponse,
    MonitorConfigItem,
    MonitorDeleteResponse,
    SystemScanContractItem,
    SystemScanProgressItem,
    SystemConnectRequest,
    SystemConnectResponse,
)
from .monitoring import (
    build_monitor_disabled_note,
    build_monitor_not_found_note,
    build_monitor_saved_note,
    default_monitor_window_hours,
    format_user_facing_chat_label,
    format_monitor_moment,
    format_monitor_next_check,
    format_monitor_interval,
    format_monitor_window,
    scenario_to_monitor_type,
    service_monitor_window_to_user_hours,
    user_monitor_window_to_service_hours,
)
from .point_delivery import get_point_report_chat
from .scenario_engine import scenario_engine
from .stoplist_digest import (
    build_stoplist_digest_snapshot,
    describe_open_stoplist_incident,
    format_stoplist_digest_text,
)
from .stoplist_skill import build_stoplist_skill_snapshot, format_stoplist_skill_answer
from .system_catalog import build_scan_contract_payload, capability_labels, orientation_summary, resolve_system_descriptor

logger = logging.getLogger(__name__)
_MONITOR_RETRY_STATUSES = {
    "failed",
    "error",
    "system_not_connected",
    "no_systems_connected",
    "system_not_found",
    "needs_point",
    "needs_period",
    "awaiting_user_input",
    "not_configured",
}


class DataAgentService:
    _SCAN_PROGRESS_STATUS_LABELS = {
        "not_started": "ещё не начинали",
        "in_progress": "идёт scan",
        "mapped": "карта системы собрана",
        "blocked": "нужна ручная проверка",
    }

    @staticmethod
    def _merge_answer_with_monitor_note(answer: str, monitor_note: str | None) -> str:
        normalized_answer = (answer or "").strip()
        normalized_note = (monitor_note or "").strip()
        if not normalized_note:
            return normalized_answer or "Не удалось сформировать ответ."
        if not normalized_answer:
            return normalized_note
        return f"{normalized_note}\n\nТекущий срез по запросу:\n{normalized_answer}"

    @staticmethod
    def _plain_monitor_type_label(monitor_type: str) -> str:
        labels = {
            "blanks": "бланки",
            "stoplist": "стоп-лист",
            "reviews": "отзывы",
        }
        return labels.get(monitor_type, monitor_type)

    @staticmethod
    def _plain_monitor_type_genitive_label(monitor_type: str) -> str:
        labels = {
            "blanks": "бланков",
            "stoplist": "стоп-листа",
            "reviews": "отзывов",
        }
        return labels.get(monitor_type, monitor_type)

    @classmethod
    def _scan_progress_status_label(cls, status: str | None) -> str:
        normalized = str(status or "not_started").strip().lower()
        return cls._SCAN_PROGRESS_STATUS_LABELS.get(normalized, "состояние не уточнено")

    @classmethod
    def _default_scan_progress_payload(cls, descriptor) -> dict[str, Any]:
        contract = build_scan_contract_payload(descriptor)
        steps = list(contract.get("scan_steps") or ())
        first_step = steps[0] if steps else {}
        return {
            "status": "not_started",
            "status_label": cls._scan_progress_status_label("not_started"),
            "current_step_id": None,
            "current_step_label": None,
            "next_step_id": str(first_step.get("step_id") or "") or None,
            "next_step_label": str(first_step.get("label") or "") or None,
            "discovered_entities": [],
            "discovered_sections": [],
            "evidence_summary": None,
            "blocked_reason": None,
            "last_scanned_at": None,
        }

    @classmethod
    def _normalize_scan_progress_payload(cls, descriptor, payload: Any) -> dict[str, Any]:
        default_payload = cls._default_scan_progress_payload(descriptor)
        raw_payload = payload if isinstance(payload, dict) else {}
        normalized_status = str(raw_payload.get("status") or default_payload["status"]).strip().lower() or "not_started"

        def _clean_text(value: Any) -> str | None:
            text = str(value or "").strip()
            return text or None

        def _clean_list(value: Any) -> list[str]:
            if not isinstance(value, (list, tuple)):
                return []
            items: list[str] = []
            for item in value:
                text = _clean_text(item)
                if text:
                    items.append(text)
            return items

        last_scanned_at = raw_payload.get("last_scanned_at")
        if isinstance(last_scanned_at, datetime):
            last_scanned_at = last_scanned_at.isoformat()
        elif last_scanned_at is not None:
            last_scanned_at = _clean_text(last_scanned_at)

        return {
            "status": normalized_status,
            "status_label": cls._scan_progress_status_label(normalized_status),
            "current_step_id": _clean_text(raw_payload.get("current_step_id")),
            "current_step_label": _clean_text(raw_payload.get("current_step_label")),
            "next_step_id": _clean_text(raw_payload.get("next_step_id")) or default_payload["next_step_id"],
            "next_step_label": _clean_text(raw_payload.get("next_step_label")) or default_payload["next_step_label"],
            "discovered_entities": _clean_list(raw_payload.get("discovered_entities")),
            "discovered_sections": _clean_list(raw_payload.get("discovered_sections")),
            "evidence_summary": _clean_text(raw_payload.get("evidence_summary")),
            "blocked_reason": _clean_text(raw_payload.get("blocked_reason")),
            "last_scanned_at": last_scanned_at,
        }

    @classmethod
    def _build_system_metadata_payload(cls, descriptor, existing_metadata: Any = None) -> dict[str, Any]:
        existing = existing_metadata if isinstance(existing_metadata, dict) else {}
        metadata_payload = {
            **existing,
            "phase": 2,
            "catalog_title": descriptor.title,
            "catalog_family": descriptor.family,
            "entry_surface": descriptor.entry_surface,
            "supports_scan": descriptor.supports_scan,
            "supports_points": descriptor.supports_points,
            "supports_monitoring": descriptor.supports_monitoring,
            "supports_chat_delivery": descriptor.supports_chat_delivery,
        }
        metadata_payload["scan_progress"] = cls._normalize_scan_progress_payload(
            descriptor,
            existing.get("scan_progress"),
        )
        return metadata_payload

    def _build_monitor_disable_clarification(self, *, point_name: str, monitor_types: list[str]) -> str:
        labels = [self._plain_monitor_type_label(item) for item in monitor_types]
        if len(labels) == 2:
            options = " или ".join(labels)
        else:
            options = ", ".join(labels)
        return (
            f"По точке {point_name} включено несколько мониторингов: {options}. "
            f"Уточни, что отключить: например, «не присылай бланки по {point_name}»."
        )

    def _build_monitor_disabled_many_note(
        self,
        *,
        monitor_type: str | None,
        count: int,
        point_name: str | None = None,
    ) -> str:
        if count <= 0:
            if monitor_type:
                return f"Активные мониторинги {self._plain_monitor_type_label(monitor_type)} сейчас не найдены."
            if point_name:
                return f"Активный мониторинг по точке {point_name} сейчас не найден."
            return "Активные мониторинги сейчас не найдены."

        if point_name and monitor_type:
            return build_monitor_disabled_note(monitor_type=monitor_type, point_name=point_name)
        if point_name:
            return f"Отключил все мониторинги по точке {point_name}."
        if monitor_type:
            return f"Отключил все мониторинги {self._plain_monitor_type_genitive_label(monitor_type)}."
        return "Отключил выбранные мониторинги."

    def _build_monitor_update_clarification(self, *, point_name: str, monitor_types: list[str]) -> str:
        labels = [self._plain_monitor_type_label(item) for item in monitor_types]
        if len(labels) == 2:
            options = " или ".join(labels)
        else:
            options = ", ".join(labels)
        return (
            f"По точке {point_name} включено несколько мониторингов: {options}. "
            f"Уточни, что изменить: например, «измени окно бланков по {point_name} с 10 до 22»."
        )

    def _scenario_for_monitor_type(self, monitor_type: str | None) -> str:
        scenarios = {
            "blanks": "blanks_report",
            "stoplist": "stoplist_report",
            "reviews": "reviews_report",
        }
        return scenarios.get(str(monitor_type or ""), "monitor_management")

    def _disable_monitor(
        self,
        *,
        user_id: int,
        scenario: str,
        point_name: str | None,
        all_monitor_types: bool = False,
        all_points: bool = False,
    ) -> str:
        monitor_type = scenario_to_monitor_type(scenario)
        if not point_name and not (monitor_type and all_points):
            return "Не хватает точки для отключения мониторинга. Пришли город и адрес пиццерии одним сообщением."

        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                if monitor_type:
                    if all_points:
                        return self._build_monitor_disabled_many_note(monitor_type=monitor_type, count=0)
                    return build_monitor_not_found_note(monitor_type=monitor_type, point_name=point_name or "")
                return f"Активный мониторинг по точке {point_name} сейчас не найден."

            if monitor_type and all_points:
                candidates = (
                    db.query(DataAgentMonitorConfig)
                    .filter(
                        DataAgentMonitorConfig.user_id == user.id,
                        DataAgentMonitorConfig.monitor_type == monitor_type,
                        DataAgentMonitorConfig.is_active == True,
                    )
                    .order_by(DataAgentMonitorConfig.point_name.asc(), DataAgentMonitorConfig.id.asc())
                    .all()
                )
                if not candidates:
                    return self._build_monitor_disabled_many_note(monitor_type=monitor_type, count=0)

                for item in candidates:
                    item.is_active = False
                db.commit()
                return self._build_monitor_disabled_many_note(
                    monitor_type=monitor_type,
                    count=len(candidates),
                )

            if not monitor_type:
                candidates = (
                    db.query(DataAgentMonitorConfig)
                    .filter(
                        DataAgentMonitorConfig.user_id == user.id,
                        DataAgentMonitorConfig.point_name == point_name,
                        DataAgentMonitorConfig.is_active == True,
                    )
                    .order_by(DataAgentMonitorConfig.monitor_type.asc(), DataAgentMonitorConfig.id.asc())
                    .all()
                )
                if not candidates:
                    return f"Активный мониторинг по точке {point_name} сейчас не найден."

                monitor_types = sorted({str(item.monitor_type) for item in candidates})
                if len(monitor_types) > 1 and not all_monitor_types:
                    return self._build_monitor_disable_clarification(
                        point_name=point_name or "",
                        monitor_types=monitor_types,
                    )

                for item in candidates:
                    item.is_active = False
                db.commit()
                if len(monitor_types) == 1:
                    return build_monitor_disabled_note(monitor_type=monitor_types[0], point_name=point_name or "")
                return self._build_monitor_disabled_many_note(
                    monitor_type=None,
                    count=len(candidates),
                    point_name=point_name,
                )

            item = (
                db.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.user_id == user.id,
                    DataAgentMonitorConfig.monitor_type == monitor_type,
                    DataAgentMonitorConfig.point_name == point_name,
                    DataAgentMonitorConfig.is_active == True,
                )
                .first()
            )
            if not item:
                return build_monitor_not_found_note(monitor_type=monitor_type, point_name=point_name or "")

            item.is_active = False
            db.commit()
            return build_monitor_disabled_note(monitor_type=monitor_type, point_name=point_name or "")
        except Exception:
            db.rollback()
            logger.exception("Failed to disable monitor")
            return "Не удалось отключить мониторинг. Попробуйте позже."
        finally:
            db.close()

    def _update_monitor_settings(
        self,
        *,
        user_id: int,
        scenario: str,
        point_name: str,
        interval_minutes: int | None,
        interval_source: str | None = None,
        start_hour: int | None = None,
        end_hour: int | None = None,
    ) -> str:
        monitor_type = scenario_to_monitor_type(scenario)
        if monitor_type:
            note = self._upsert_monitor(
                user_id=user_id,
                scenario=scenario,
                point_name=point_name,
                interval_minutes=interval_minutes,
                interval_source=interval_source,
                start_hour=start_hour,
                end_hour=end_hour,
            )
            return note or "Не удалось обновить мониторинг. Попробуйте указать точку одним сообщением."

        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return f"Активный мониторинг по точке {point_name} сейчас не найден."

            candidates = (
                db.query(DataAgentMonitorConfig)
                .filter(
                    DataAgentMonitorConfig.user_id == user.id,
                    DataAgentMonitorConfig.point_name == point_name,
                    DataAgentMonitorConfig.is_active == True,
                )
                .order_by(DataAgentMonitorConfig.monitor_type.asc(), DataAgentMonitorConfig.id.asc())
                .all()
            )
            if not candidates:
                return f"Активный мониторинг по точке {point_name} сейчас не найден."

            monitor_types = sorted({str(item.monitor_type) for item in candidates})
            if len(monitor_types) > 1:
                return self._build_monitor_update_clarification(
                    point_name=point_name,
                    monitor_types=monitor_types,
                )
            resolved_scenario = self._scenario_for_monitor_type(monitor_types[0])
        finally:
            db.close()

        note = self._upsert_monitor(
            user_id=user_id,
            scenario=resolved_scenario,
            point_name=point_name,
            interval_minutes=interval_minutes,
            interval_source=interval_source,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        return note or "Не удалось обновить мониторинг. Попробуйте указать тип отчёта и точку одним сообщением."

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

            descriptor = resolve_system_descriptor(url=str(payload.url))
            system_name = descriptor.system_name

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
                metadata_payload = self._build_system_metadata_payload(descriptor, existing.metadata_json)
                existing.system_name = system_name
                existing.encrypted_password = encrypted_password
                existing.is_active = True
                existing.metadata_json = metadata_payload
                existing.last_connected_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return SystemConnectResponse(success=True, system=self._to_connected_system(existing))

            metadata_payload = self._build_system_metadata_payload(descriptor)
            system = DataAgentSystem(
                user_id=user.id,
                system_name=system_name,
                url=str(payload.url),
                login=payload.username,
                encrypted_password=encrypted_password,
                secret_storage="fernet_local",
                is_active=True,
                metadata_json=metadata_payload,
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
            profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
            points = (
                db.query(SavedPoint)
                .filter(SavedPoint.user_id == user.id, SavedPoint.is_active.is_(True))
                .all()
            )
            points_by_name = {item.display_name: item for item in points}
            latest_events = self._load_latest_user_facing_events(db, items)
            open_stoplist_incidents = self._load_open_stoplist_incidents(db, items)
            monitors: List[MonitorConfigItem] = []
            for item in items:
                description = self._describe_monitor_item(
                    item,
                    latest_event=latest_events.get(item.id),
                    open_incident=open_stoplist_incidents.get(item.id),
                    delivery_label=self._resolve_monitor_delivery_label(
                        profile,
                        item.monitor_type,
                        point=points_by_name.get(item.point_name),
                    ),
                )
                monitors.append(
                    MonitorConfigItem(
                        id=item.id,
                        monitor_type=item.monitor_type,
                        point_name=item.point_name,
                        check_interval_minutes=item.check_interval_minutes,
                        is_active=item.is_active,
                        last_status=item.last_status,
                        last_checked_at=item.last_checked_at,
                        interval_label=description["interval_label"],
                        window_label=description["window_label"],
                        status_label=description["status_label"],
                        last_checked_label=description["last_checked_label"],
                        next_check_label=description["next_check_label"],
                        last_event_title=description["last_event_title"],
                        last_event_label=description["last_event_label"],
                        incident_label=description["incident_label"],
                        manager_status_label=description["manager_status_label"],
                        delivery_label=description["delivery_label"],
                        behavior_label=description["behavior_label"],
                        status_icon=description["status_icon"],
                        status_tone=description["status_tone"],
                        has_active_alert=description["has_active_alert"],
                    )
                )
            return monitors
        finally:
            db.close()

    def _build_monitors_summary(self, user_id: int) -> str:
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return "Активных мониторингов сейчас нет."

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
            if not items:
                return (
                    "Активных мониторингов сейчас нет.\n\n"
                    "Можно написать: Присылай мне бланки по Сухой Лог Белинского 40 каждые 3 часа."
                )

            profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
            points = (
                db.query(SavedPoint)
                .filter(SavedPoint.user_id == user.id, SavedPoint.is_active.is_(True))
                .all()
            )
            points_by_name = {item.display_name: item for item in points}
            latest_events = self._load_latest_user_facing_events(db, items)
            open_stoplist_incidents = self._load_open_stoplist_incidents(db, items)
            described_items: list[tuple[DataAgentMonitorConfig, dict[str, object]]] = []
            for item in items:
                described_items.append(
                    (
                        item,
                        self._describe_monitor_item(
                            item,
                            latest_event=latest_events.get(item.id),
                            open_incident=open_stoplist_incidents.get(item.id),
                            delivery_label=self._resolve_monitor_delivery_label(
                                profile,
                                item.monitor_type,
                                point=points_by_name.get(item.point_name),
                            ),
                        ),
                    )
                )

            active_alert_count = sum(1 for _, description in described_items if bool(description["has_active_alert"]))
            retry_count = sum(1 for _, description in described_items if description["status_tone"] == "retry")
            lines = [f"Активные мониторинги: {len(described_items)}"]
            if active_alert_count:
                lines.append(f"🔴 Красная зона сейчас: {active_alert_count}")
            if retry_count:
                lines.append(f"🟡 Нужна повторная проверка: {retry_count}")
            lines.append("")

            for index, (item, description) in enumerate(described_items):
                lines.append(self._format_monitor_summary_item(item, description=description))
                if index < len(described_items) - 1:
                    lines.append("")

            lines.extend(
                [
                    "",
                    "Изменить: присылай бланки по Сухой Лог Белинского 40 каждые 3 часа с 10 до 22.",
                    "Отключить: не присылай бланки по Сухой Лог Белинского 40.",
                ]
            )
            return "\n".join(lines)
        except Exception:
            logger.exception("Failed to build monitors summary")
            return "Не удалось получить список мониторингов. Попробуйте позже."
        finally:
            db.close()

    def _format_monitor_summary_item(
        self,
        item: DataAgentMonitorConfig,
        *,
        latest_event: DataAgentMonitorEvent | None = None,
        open_incident: StopListIncident | None = None,
        delivery_label: str | None = None,
        description: dict[str, object] | None = None,
    ) -> str:
        description = description or self._describe_monitor_item(
            item,
            latest_event=latest_event,
            open_incident=open_incident,
            delivery_label=delivery_label,
        )
        details = [description["interval_label"]]
        if description["window_label"]:
            details.append(description["window_label"])
        lines = [
            f"{description['status_icon']} {description['monitor_label']} — {item.point_name}",
            f"  {'; '.join(details)}",
            f"  Сейчас: {description['status_label']}",
            f"  Проверка: {description['last_checked_label']}; дальше: {description['next_check_label']}",
        ]
        if description["incident_label"]:
            lines.append(f"  Инцидент: {description['incident_label']}")
        if description["behavior_label"]:
            lines.append(f"  Пришлю: {description['behavior_label']}")
        if description["last_event_label"]:
            lines.append(f"  {description['last_event_title']}: {description['last_event_label']}")
        if description["delivery_label"]:
            lines.append(f"  Куда: {description['delivery_label']}")
        return "\n".join(lines)

    def _describe_monitor_item(
        self,
        item: DataAgentMonitorConfig,
        *,
        latest_event: DataAgentMonitorEvent | None = None,
        open_incident: StopListIncident | None = None,
        delivery_label: str | None = None,
    ) -> dict[str, object]:
        labels = {
            "blanks": "Бланки",
            "stoplist": "Стоп-лист",
            "reviews": "Отзывы",
        }
        monitor_label = labels.get(item.monitor_type, "Мониторинг")
        interval_label = format_monitor_interval(item.check_interval_minutes)
        window_label: str | None = None
        if item.active_from_hour is not None and item.active_to_hour is not None:
            start_hour, end_hour = service_monitor_window_to_user_hours(
                item.active_from_hour,
                item.active_to_hour,
            )
            window_label = format_monitor_window(start_hour, end_hour)
        has_active_alert = self._monitor_has_active_alert(item)
        incident_meta = None
        if item.monitor_type == "stoplist":
            incident_meta = describe_open_stoplist_incident(open_incident)
        status_meta = self._describe_monitor_status(
            item,
            has_active_alert=has_active_alert,
            incident_meta=incident_meta,
        )
        status_label = status_meta["label"]
        behavior_label = self._format_monitor_behavior(item)
        last_checked_label = format_monitor_moment(item.last_checked_at)
        next_check_label = format_monitor_next_check(
            check_interval_minutes=item.check_interval_minutes,
            active_from_hour=item.active_from_hour,
            active_to_hour=item.active_to_hour,
            last_checked_at=item.last_checked_at,
        )
        last_event_meta = self._describe_monitor_event(item, latest_event)
        return {
            "monitor_label": monitor_label,
            "interval_label": interval_label,
            "window_label": window_label,
            "status_label": status_label,
            "status_icon": self._monitor_status_icon(status_meta["tone"]),
            "status_tone": status_meta["tone"],
            "behavior_label": behavior_label,
            "last_checked_label": last_checked_label,
            "next_check_label": next_check_label,
            "last_event_title": last_event_meta["title"],
            "last_event_label": last_event_meta["label"],
            "incident_label": incident_meta["incident_label"] if incident_meta else None,
            "manager_status_label": incident_meta["manager_status_label"] if incident_meta else None,
            "delivery_label": delivery_label,
            "has_active_alert": has_active_alert,
        }

    def _monitor_has_active_alert(self, item: DataAgentMonitorConfig) -> bool:
        if item.monitor_type != "blanks":
            return False
        return bool(isinstance(item.last_result_json, dict) and item.last_result_json.get("has_red_flags"))

    def _describe_monitor_status(
        self,
        item: DataAgentMonitorConfig,
        *,
        has_active_alert: bool = False,
        incident_meta: dict[str, str] | None = None,
    ) -> dict[str, str]:
        if has_active_alert:
            return {"label": "есть красная зона", "tone": "alert"}
        if item.monitor_type == "stoplist" and incident_meta:
            return {
                "label": str(incident_meta.get("status_label") or "есть открытый стоп-лист"),
                "tone": str(incident_meta.get("status_tone") or "notice"),
            }

        normalized = (item.last_status or "").strip().lower()
        if not normalized:
            return {"label": "ещё не было", "tone": "pending"}
        if normalized in {"ok", "completed"}:
            if item.monitor_type == "blanks":
                return {"label": "красных зон нет", "tone": "ok"}
            if item.monitor_type == "stoplist":
                return {"label": "отчёт получен", "tone": "ok"}
            if item.monitor_type == "reviews":
                return {"label": "отчёт обновлён", "tone": "ok"}
            return {"label": "прошла", "tone": "ok"}
        if normalized in _MONITOR_RETRY_STATUSES:
            return {"label": "нужна повторная проверка", "tone": "retry"}
        if normalized in {"alert", "warning", "changed", "red_alert"}:
            return {"label": "есть уведомление", "tone": "notice"}
        return {"label": "обновлён", "tone": "info"}

    def _format_monitor_status(self, item: DataAgentMonitorConfig, *, has_active_alert: bool = False) -> str:
        return self._describe_monitor_status(item, has_active_alert=has_active_alert)["label"]

    @staticmethod
    def _monitor_status_icon(tone: str) -> str:
        return {
            "alert": "🔴",
            "retry": "🟡",
            "pending": "⚪",
            "ok": "✅",
            "notice": "🔔",
            "info": "ℹ️",
        }.get(tone, "ℹ️")

    def _format_monitor_behavior(self, item: DataAgentMonitorConfig) -> str:
        if item.monitor_type == "blanks":
            return "сразу сообщу, если появится красная зона"
        if item.monitor_type == "stoplist":
            return "пришлю изменения по стоп-листу и плановые сводки"
        if item.monitor_type == "reviews":
            return "пришлю новые отзывы и плановые сводки"
        return "пришлю новые события по мониторингу"

    def _load_open_stoplist_incidents(
        self,
        db,
        items: List[DataAgentMonitorConfig],
    ) -> dict[int, StopListIncident]:
        stoplist_config_ids = [int(item.id) for item in items if item.monitor_type == "stoplist" and item.id]
        if not stoplist_config_ids:
            return {}

        rows = (
            db.query(StopListIncident)
            .filter(
                StopListIncident.monitor_config_id.in_(stoplist_config_ids),
                StopListIncident.status == "open",
            )
            .order_by(StopListIncident.monitor_config_id.asc(), StopListIncident.last_seen_at.desc(), StopListIncident.id.desc())
            .all()
        )

        incidents: dict[int, StopListIncident] = {}
        for row in rows:
            config_id = int(row.monitor_config_id or 0)
            if config_id and config_id not in incidents:
                incidents[config_id] = row
        return incidents

    @staticmethod
    def _resolve_stoplist_digest_days(period_hint: str | None) -> int:
        normalized = str(period_hint or "").strip().lower()
        if "сутк" in normalized or "день" in normalized:
            return 1
        return 7

    @staticmethod
    def _contains_stoplist_intent_text(message: str) -> bool:
        lowered = str(message or "").strip().lower()
        return any(
            token in lowered
            for token in (
                "стоп-лист",
                "стоп лист",
                "стоплист",
                "по стопам",
                "стопы",
                "стопам",
                "стопах",
                "недоступн",
                "нет в наличии",
            )
        )

    @staticmethod
    def _contains_stoplist_digest_intent_text(message: str) -> bool:
        lowered = str(message or "").strip().lower()
        if not DataAgentService._contains_stoplist_intent_text(lowered):
            return False
        has_digest_marker = any(
            token in lowered
            for token in (
                "дайджест",
                "digest",
                "сводк",
                "резюме",
                "итоги",
                "что было",
                "как прошла неделя",
            )
        )
        has_period_marker = any(
            token in lowered
            for token in (
                "недел",
                "7 дней",
                "за неделю",
                "за последнюю неделю",
                "еженедель",
            )
        )
        return has_digest_marker and has_period_marker

    @staticmethod
    def _contains_stoplist_skill_intent_text(message: str) -> bool:
        lowered = str(message or "").strip().lower()
        if not DataAgentService._contains_stoplist_intent_text(lowered):
            return False
        if any(
            token in lowered
            for token in (
                "покажи стоп-лист",
                "покажи стоплист",
                "собери стоп-лист",
                "отчет по стоп-листу",
                "отчёт по стоп-листу",
                "список позиций",
            )
        ):
            return False
        return any(
            token in lowered
            for token in (
                "что по стоп",
                "что со стоп",
                "статус по стоп",
                "статус кейс",
                "кейсы по стоп",
                "какие кейсы",
                "требует реакции",
                "требуют реакции",
                "нужна помощь",
                "нужны помощь",
                "в работе",
                "открытые кейсы",
                "открытый кейс",
                "открытые проблемы",
                "нормализов",
                "закрыт",
                "закрытые кейсы",
                "приоритет по стоп",
            )
        )

    @staticmethod
    def _extract_stoplist_skill_focus(message: str, *, point_name: str | None = None) -> str:
        lowered = str(message or "").strip().lower()
        if any(token in lowered for token in ("требует реакции", "требуют реакции", "нужна помощь", "эскал")):
            return "attention"
        if point_name and any(token in lowered for token in ("статус", "что по стоп", "что со стоп", "кейс", "по точке")):
            return "point_status"
        return "overview"

    def _maybe_override_stoplist_skill(self, decision: AgentDecision, message: str) -> AgentDecision:
        if decision.scenario == "stoplist_digest":
            return decision
        if self._contains_stoplist_digest_intent_text(message):
            return decision
        if not self._contains_stoplist_skill_intent_text(message):
            return decision

        slots = dict(decision.slots or {})
        point_name = slots.get("point_name")
        slots["source_message"] = message
        slots["stoplist_skill_focus"] = self._extract_stoplist_skill_focus(
            message,
            point_name=point_name if isinstance(point_name, str) else None,
        )
        return AgentDecision(
            scenario="stoplist_skill",
            selected_tools=["orchestrator"],
            slots=slots,
            missing_slots=[],
            reasoning="StopListSkill override",
            response_style=decision.response_style,
        )

    def _build_stoplist_digest(self, user_id: int, *, period_hint: str | None = None) -> str:
        days = self._resolve_stoplist_digest_days(period_hint)
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return f"За последние {days} дней по стоп-листу инцидентов не было."

            since = datetime.utcnow() - timedelta(days=days)
            incidents = (
                db.query(StopListIncident)
                .filter(
                    StopListIncident.user_id == user.id,
                    StopListIncident.last_seen_at >= since,
                )
                .order_by(StopListIncident.last_seen_at.desc(), StopListIncident.id.desc())
                .all()
            )
            snapshot = build_stoplist_digest_snapshot(incidents, days=days)
            return format_stoplist_digest_text(snapshot)
        except Exception:
            logger.exception("Failed to build stoplist digest")
            return "Не удалось собрать digest по стоп-листу. Попробуйте позже."
        finally:
            db.close()

    def _build_stoplist_skill(
        self,
        user_id: int,
        *,
        point_name: str | None = None,
        focus: str | None = None,
        period_hint: str | None = None,
    ) -> str:
        days = self._resolve_stoplist_digest_days(period_hint)
        db = get_db_session()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                snapshot = build_stoplist_skill_snapshot([], days=days)
                return format_stoplist_skill_answer(
                    snapshot,
                    focus=focus or "overview",
                    point_name=point_name,
                )

            since = datetime.utcnow() - timedelta(days=days)
            incidents_query = (
                db.query(StopListIncident)
                .filter(
                    StopListIncident.user_id == user.id,
                    StopListIncident.last_seen_at >= since,
                )
                .order_by(StopListIncident.last_seen_at.desc(), StopListIncident.id.desc())
            )
            if point_name:
                incidents_query = incidents_query.filter(StopListIncident.point_name == point_name)

            incidents = incidents_query.all()
            snapshot = build_stoplist_skill_snapshot(incidents, days=days)
            return format_stoplist_skill_answer(
                snapshot,
                focus=focus or "overview",
                point_name=point_name,
            )
        except Exception:
            logger.exception("Failed to build stoplist skill answer")
            return "Не удалось собрать статус по стоп-листу. Попробуйте позже."
        finally:
            db.close()

    def _load_latest_user_facing_events(
        self,
        db,
        items: List[DataAgentMonitorConfig],
    ) -> dict[int, DataAgentMonitorEvent]:
        config_ids = [item.id for item in items if item.id]
        if not config_ids:
            return {}

        rows = (
            db.query(DataAgentMonitorEvent)
            .filter(DataAgentMonitorEvent.config_id.in_(config_ids))
            .order_by(DataAgentMonitorEvent.config_id.asc(), DataAgentMonitorEvent.created_at.desc())
            .all()
        )

        grouped: dict[int, list[DataAgentMonitorEvent]] = {}
        for row in rows:
            grouped.setdefault(int(row.config_id), []).append(row)

        latest_events: dict[int, DataAgentMonitorEvent] = {}
        for item in items:
            event = self._pick_user_facing_event(
                grouped.get(int(item.id), []),
                monitor_type=item.monitor_type,
                last_status=item.last_status,
            )
            if event is not None:
                latest_events[int(item.id)] = event
        return latest_events

    def _pick_user_facing_event(
        self,
        events: List[DataAgentMonitorEvent],
        *,
        monitor_type: str,
        last_status: str | None = None,
    ) -> DataAgentMonitorEvent | None:
        if not events:
            return None

        latest_event = events[0]
        normalized_status = (last_status or "").lower()
        if normalized_status in _MONITOR_RETRY_STATUSES and (
            (latest_event.severity or "").lower() == "error"
        ):
            return latest_event

        if monitor_type == "blanks":
            for item in events:
                if (item.severity or "").lower() == "critical":
                    return item
            return None

        for item in events:
            if (item.severity or "").lower() != "error":
                return item
        return None

    def _describe_monitor_event(
        self,
        item: DataAgentMonitorConfig,
        latest_event: DataAgentMonitorEvent | None,
    ) -> dict[str, str]:
        if latest_event is None:
            return {"title": "Последнее уведомление", "label": "пока не было"}

        event_time = format_monitor_moment(latest_event.created_at)
        sent_to_telegram = bool(latest_event.sent_to_telegram)
        severity = (latest_event.severity or "").lower()
        if severity == "error":
            return {
                "title": "Последнее событие",
                "label": f"{event_time}, проверка не завершилась, повторим автоматически",
            }
        title = "Последнее уведомление" if sent_to_telegram else "Последнее событие"
        if item.monitor_type == "blanks":
            label = f"{event_time}, {'была красная зона' if sent_to_telegram else 'зафиксирована красная зона'}"
            return {"title": title, "label": label}
        if item.monitor_type in {"stoplist", "reviews"}:
            label = f"{event_time}, {'отчёт был отправлен' if sent_to_telegram else 'отчёт сформирован'}"
            return {"title": title, "label": label}
        label = f"{event_time}, {'было уведомление' if sent_to_telegram else 'событие зафиксировано'}"
        return {"title": title, "label": label}

    def _resolve_monitor_delivery_label(
        self,
        profile: DataAgentProfile | None,
        monitor_type: str,
        *,
        point: SavedPoint | None = None,
    ) -> str | None:
        point_chat_id, point_chat_title = get_point_report_chat(point, monitor_type)
        if point_chat_id:
            return format_user_facing_chat_label(point_chat_title)

        if profile is None:
            return None

        title_fields = {
            "reviews": ("reviews_report_chat_id", "reviews_report_chat_title"),
            "stoplist": ("stoplist_report_chat_id", "stoplist_report_chat_title"),
            "blanks": ("blanks_report_chat_id", "blanks_report_chat_title"),
        }
        selected = title_fields.get(monitor_type)
        if selected:
            category_chat_id = getattr(profile, selected[0], None)
            category_chat_title = getattr(profile, selected[1], None)
            if category_chat_id:
                return format_user_facing_chat_label(category_chat_title)

        if profile.default_report_chat_id:
            return format_user_facing_chat_label(profile.default_report_chat_title)
        return None

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
        interval_minutes: int | None,
        interval_source: str | None = None,
        start_hour: int | None = None,
        end_hour: int | None = None,
    ) -> str | None:
        monitor_type = scenario_to_monitor_type(scenario)
        if scenario == "reviews_report" and interval_minutes:
            monitor_type = "reviews"
            point_name = point_name or "все точки"

        if not monitor_type or not point_name:
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
            had_existing = existing is not None
            was_active = bool(existing and existing.is_active)
            previous_interval = existing.check_interval_minutes if existing else None
            previous_user_window: tuple[int, int] | None = None
            if existing and existing.active_from_hour is not None and existing.active_to_hour is not None:
                previous_user_window = service_monitor_window_to_user_hours(
                    existing.active_from_hour,
                    existing.active_to_hour,
                )

            resolved_interval_minutes = interval_minutes
            if existing and (interval_minutes is None or interval_source == "default_intent"):
                resolved_interval_minutes = existing.check_interval_minutes
            elif resolved_interval_minutes is None:
                resolved_interval_minutes = 180

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
                    check_interval_minutes=int(resolved_interval_minutes),
                    is_active=True,
                    active_from_hour=service_start_hour,
                    active_to_hour=service_end_hour,
                )
                db.add(existing)
            else:
                existing.check_interval_minutes = int(resolved_interval_minutes)
                existing.is_active = True
                if start_hour is not None and end_hour is not None:
                    existing.active_from_hour = service_start_hour
                    existing.active_to_hour = service_end_hour
                elif existing.active_from_hour is None or existing.active_to_hour is None:
                    existing.active_from_hour = service_start_hour
                    existing.active_to_hour = service_end_hour

            profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
            chat_title = profile.default_report_chat_title if profile else None
            note_action = "enabled"
            if had_existing and was_active:
                interval_changed = previous_interval != resolved_interval_minutes
                window_changed = previous_user_window != user_window
                note_action = "updated" if interval_changed or window_changed else "already_configured"
            db.commit()
            return build_monitor_saved_note(
                monitor_type=monitor_type,
                point_name=point_name,
                interval_minutes=int(resolved_interval_minutes),
                chat_title=chat_title,
                start_hour=user_window[0],
                end_hour=user_window[1],
                action=note_action,
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
            decision = self._maybe_override_stoplist_skill(decision, normalized_message)
            selected_tools = decision.selected_tools

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

            monitor_action = str(decision.slots.get("monitor_action") or "").strip().lower()
            point_name = decision.slots.get("point_name")
            if decision.scenario == "stoplist_digest":
                answer = self._build_stoplist_digest(
                    payload.user_id,
                    period_hint=decision.slots.get("period_hint"),
                )
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    debug_summary=debug_summary,
                )

            if decision.scenario == "stoplist_skill":
                answer = self._build_stoplist_skill(
                    payload.user_id,
                    point_name=point_name if isinstance(point_name, str) else None,
                    focus=decision.slots.get("stoplist_skill_focus"),
                    period_hint=decision.slots.get("period_hint"),
                )
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    debug_summary=debug_summary,
                )

            if monitor_action == "list":
                answer = self._build_monitors_summary(payload.user_id)
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    debug_summary=debug_summary,
                )

            if monitor_action == "disable" and (point_name or decision.slots.get("all_points")):
                answer = self._disable_monitor(
                    user_id=payload.user_id,
                    scenario=decision.scenario,
                    point_name=point_name,
                    all_monitor_types=bool(decision.slots.get("all_monitor_types")),
                    all_points=bool(decision.slots.get("all_points")),
                )
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    debug_summary=debug_summary,
                )

            if monitor_action == "update" and point_name:
                interval_minutes = decision.slots.get("monitor_interval_minutes")
                if not isinstance(interval_minutes, int) or interval_minutes <= 0:
                    interval_minutes = None
                answer = self._update_monitor_settings(
                    user_id=payload.user_id,
                    scenario=decision.scenario,
                    point_name=point_name,
                    interval_minutes=interval_minutes,
                    interval_source=decision.slots.get("monitor_interval_source"),
                    start_hour=decision.slots.get("monitor_start_hour"),
                    end_hour=decision.slots.get("monitor_end_hour"),
                )
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    debug_summary=debug_summary,
                )

            if monitor_action == "enable" and point_name:
                interval_minutes = decision.slots.get("monitor_interval_minutes")
                if not isinstance(interval_minutes, int) or interval_minutes <= 0:
                    interval_minutes = None
                answer = self._upsert_monitor(
                    user_id=payload.user_id,
                    scenario=decision.scenario,
                    point_name=point_name,
                    interval_minutes=interval_minutes,
                    interval_source=decision.slots.get("monitor_interval_source"),
                    start_hour=decision.slots.get("monitor_start_hour"),
                    end_hour=decision.slots.get("monitor_end_hour"),
                )
                if not answer:
                    answer = "Не удалось настроить мониторинг. Попробуйте указать тип отчёта и точку одним сообщением."
                debug_payload, debug_summary = build_debug_artifacts(
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
                    selected_tools=selected_tools,
                    tool_results={},
                )
                agent_runtime.save_session(
                    payload.user_id,
                    decision,
                    user_message=normalized_message,
                    answer=answer,
                    status="completed",
                    trace_id=trace_id,
                    debug_summary=debug_summary,
                    debug_payload=debug_payload,
                )
                return DataAgentChatResponse(
                    answer=answer,
                    selected_tools=selected_tools,
                    trace_id=trace_id,
                    scenario=decision.scenario,
                    status="completed",
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
                    interval_source=decision.slots.get("monitor_interval_source"),
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
            fallback_answer = "Не удалось выполнить запрос. Попробуйте повторить чуть позже."
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
        descriptor = resolve_system_descriptor(system_name=system.system_name, url=system.url)
        metadata = system.metadata_json if isinstance(system.metadata_json, dict) else {}
        return ConnectedSystem(
            system_id=str(system.id),
            user_id=system.user.telegram_id if system.user else system.user_id,
            system_name=descriptor.system_name,
            system_title=descriptor.title,
            system_family=descriptor.family,
            entry_surface=descriptor.entry_surface,
            point_entity_label=descriptor.point_entity_label,
            url=system.url,
            login=system.login,
            is_active=system.is_active,
            supports_scan=descriptor.supports_scan,
            supports_points=descriptor.supports_points,
            supports_monitoring=descriptor.supports_monitoring,
            supports_chat_delivery=descriptor.supports_chat_delivery,
            capability_labels=capability_labels(descriptor),
            scan_order=list(descriptor.scan_order),
            orientation_summary=orientation_summary(descriptor),
            next_step_hint=descriptor.next_step_hint or None,
            scan_contract=SystemScanContractItem(**build_scan_contract_payload(descriptor)),
            scan_progress=SystemScanProgressItem(
                **self._normalize_scan_progress_payload(descriptor, metadata.get("scan_progress"))
            ),
            created_at=system.created_at,
        )


service = DataAgentService()
