from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from db.models import DataAgentMonitorConfig, DataAgentMonitorEvent, StopListIncident

from .stoplist_task_engine import sync_stoplist_incident_task

logger = logging.getLogger(__name__)


def _normalize_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _normalize_delta(value: Any) -> dict[str, list[str]]:
    payload = value if isinstance(value, dict) else {}
    return {
        "added": _normalize_items(payload.get("added")),
        "removed": _normalize_items(payload.get("removed")),
        "stayed": _normalize_items(payload.get("stayed")),
    }


def _build_incident_title(point_name: str, lifecycle_state: str) -> str:
    if lifecycle_state == "new":
        return f"Новый стоп-лист: {point_name}"
    if lifecycle_state == "ongoing":
        return f"Стоп-лист продолжается: {point_name}"
    if lifecycle_state == "resolved":
        return f"Стоп-лист нормализовался: {point_name}"
    return f"Стоп-лист: {point_name}"


def _build_resolved_summary(point_name: str, delta: dict[str, list[str]]) -> str:
    removed = delta.get("removed") or []
    if removed:
        removed_preview = ", ".join(removed[:5])
        return f"Точка: {point_name}\nСтоп-лист нормализовался. Ушли из стопа: {removed_preview}."
    return f"Точка: {point_name}\nСтоп-лист нормализовался. Недоступных позиций не найдено."


def _extract_report_hash(result: dict[str, Any]) -> str | None:
    value = str(result.get("alert_hash") or "").strip()
    return value or None


def _extract_current_items(result: dict[str, Any]) -> list[str]:
    explicit_items = _normalize_items(result.get("items"))
    if explicit_items:
        return explicit_items

    delta = _normalize_delta(result.get("delta"))
    items = delta["stayed"] + [item for item in delta["added"] if item not in delta["stayed"]]
    return _normalize_items(items)


def _find_active_incident(db, *, user_id: int, point_name: str) -> StopListIncident | None:
    return (
        db.query(StopListIncident)
        .filter(
            StopListIncident.user_id == user_id,
            StopListIncident.point_name == point_name,
            StopListIncident.status == "open",
        )
        .order_by(StopListIncident.opened_at.desc(), StopListIncident.id.desc())
        .first()
    )


def upsert_stoplist_incident(
    db,
    *,
    config: DataAgentMonitorConfig,
    result: dict[str, Any],
    monitor_event: DataAgentMonitorEvent | None = None,
    observed_at: datetime | None = None,
) -> StopListIncident | None:
    observed_at = observed_at or datetime.utcnow()
    current_items = _extract_current_items(result)
    delta = _normalize_delta(result.get("delta"))
    report_text = str(result.get("report_text") or "").strip()
    report_hash = _extract_report_hash(result)
    active_incident = _find_active_incident(db, user_id=int(config.user_id), point_name=str(config.point_name))

    if current_items:
        if active_incident is None:
            incident = StopListIncident(
                user_id=config.user_id,
                monitor_config_id=config.id,
                first_event_id=getattr(monitor_event, "id", None),
                last_event_id=getattr(monitor_event, "id", None),
                system_name=config.system_name,
                point_name=config.point_name,
                status="open",
                lifecycle_state="new",
                manager_status="unreviewed",
                title=_build_incident_title(config.point_name, "new"),
                summary_text=report_text or f"Точка: {config.point_name}\nСтоп-лист активен.",
                current_items_json=current_items,
                last_delta_json=delta,
                last_report_hash=report_hash,
                opened_at=observed_at,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                update_count=1,
            )
            db.add(incident)
            db.flush()
            try:
                sync_stoplist_incident_task(db, incident=incident, observed_at=observed_at)
            except Exception:
                logger.exception("Failed to sync stoplist task for new incident id=%s", getattr(incident, "id", None))
            return incident

        if str(active_incident.manager_status or "").strip().lower() in {"fixed", "not_relevant"}:
            active_incident.manager_status = "unreviewed"
            active_incident.manager_note = None
            active_incident.manager_updated_at = None
            active_incident.manager_updated_by_user_id = None
            active_incident.manager_updated_chat_id = None
            active_incident.manager_updated_message_id = None
        active_incident.monitor_config_id = config.id
        active_incident.last_event_id = getattr(monitor_event, "id", None)
        active_incident.system_name = config.system_name
        active_incident.status = "open"
        active_incident.lifecycle_state = "ongoing"
        active_incident.title = _build_incident_title(config.point_name, "ongoing")
        active_incident.summary_text = report_text or active_incident.summary_text
        active_incident.current_items_json = current_items
        active_incident.last_delta_json = delta
        active_incident.last_report_hash = report_hash
        active_incident.last_seen_at = observed_at
        active_incident.resolved_at = None
        active_incident.update_count = max(int(active_incident.update_count or 0), 1) + 1
        db.flush()
        try:
            sync_stoplist_incident_task(db, incident=active_incident, observed_at=observed_at)
        except Exception:
            logger.exception("Failed to sync stoplist task for ongoing incident id=%s", getattr(active_incident, "id", None))
        return active_incident

    if active_incident is None:
        return None

    active_incident.monitor_config_id = config.id
    active_incident.last_event_id = getattr(monitor_event, "id", None)
    active_incident.system_name = config.system_name
    active_incident.status = "resolved"
    active_incident.lifecycle_state = "resolved"
    active_incident.title = _build_incident_title(config.point_name, "resolved")
    active_incident.summary_text = report_text or _build_resolved_summary(config.point_name, delta)
    active_incident.current_items_json = []
    active_incident.last_delta_json = delta
    active_incident.last_report_hash = report_hash
    active_incident.last_seen_at = observed_at
    active_incident.resolved_at = observed_at
    active_incident.update_count = max(int(active_incident.update_count or 0), 1) + 1
    db.flush()
    try:
        sync_stoplist_incident_task(db, incident=active_incident, observed_at=observed_at)
    except Exception:
        logger.exception("Failed to sync stoplist task for resolved incident id=%s", getattr(active_incident, "id", None))
    return active_incident
