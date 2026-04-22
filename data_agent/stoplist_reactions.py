from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from db.models import SavedPoint, StopListIncident, User

from .point_delivery import find_delivery_points_for_text, normalize_delivery_text

_REACTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("escalated", ("эскал", "подними выше", "руковод", "директор", "старшему")),
    ("needs_help", ("нужна помощь", "нужен совет", "помоги", "разберись", "подскажи")),
    ("not_relevant", ("неакту", "ложн", "ошибоч", "ошибка", "само ушло", "уже не нужно")),
    ("fixed", ("исправ", "сделано", "готово", "устран", "решено", "починили", "закрыли")),
    ("accepted", ("принято", "принял", "взял", "беру", "в работе", "ок", "окей")),
)

_STATUS_RESPONSE_TEXT = {
    "accepted": "Принял. Отметил реакцию по стоп-листу для {point_name}.",
    "fixed": "Зафиксировал: исправлено по стоп-листу для {point_name}. Перепроверю по следующему циклу.",
    "not_relevant": "Отметил, что кейс по стоп-листу для {point_name} уже неактуален. Перепроверю по следующему циклу.",
    "needs_help": "Отметил, что по стоп-листу для {point_name} нужна помощь.",
    "escalated": "Зафиксировал эскалацию по стоп-листу для {point_name}.",
}

_STATUS_LABELS = {
    "unreviewed": "без реакции",
    "accepted": "принято",
    "fixed": "исправлено",
    "not_relevant": "неактуально",
    "needs_help": "нужна помощь",
    "escalated": "эскалировано",
}


@dataclass(frozen=True)
class StopListReactionResult:
    handled: bool
    matched: bool
    manager_status: str
    point_name: str | None
    response_text: str
    incident_id: int | None = None
    matched_by: str | None = None


def _normalize_text(value: str | None) -> str:
    return normalize_delivery_text(value)


def classify_stoplist_reaction(text: str | None) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    padded = f" {normalized} "
    for status, markers in _REACTION_RULES:
        for marker in markers:
            normalized_marker = _normalize_text(marker)
            if not normalized_marker:
                continue
            if f" {normalized_marker} " in padded or normalized_marker in normalized:
                return status
    return None


def format_manager_status_label(status: str | None) -> str:
    normalized = str(status or "unreviewed").strip().lower()
    return _STATUS_LABELS.get(normalized, "статус не уточнён")


def _load_open_incidents(db, *, user_id: int) -> list[StopListIncident]:
    return (
        db.query(StopListIncident)
        .filter(
            StopListIncident.user_id == user_id,
            StopListIncident.status == "open",
        )
        .order_by(StopListIncident.last_seen_at.desc(), StopListIncident.id.desc())
        .all()
    )


def _load_active_points(db, *, user_id: int) -> list[SavedPoint]:
    return (
        db.query(SavedPoint)
        .filter(
            SavedPoint.user_id == user_id,
            SavedPoint.is_active.is_(True),
        )
        .order_by(SavedPoint.id.asc())
        .all()
    )


def _incident_message_ids(incident: StopListIncident) -> set[int]:
    message_ids: set[int] = set()
    for event in (incident.first_event, incident.last_event):
        if getattr(event, "telegram_message_id", None):
            message_ids.add(int(event.telegram_message_id))
    return message_ids


def _incident_chat_ids(incident: StopListIncident) -> set[int]:
    chat_ids: set[int] = set()
    for event in (incident.first_event, incident.last_event):
        if getattr(event, "telegram_chat_id", None):
            chat_ids.add(int(event.telegram_chat_id))
    return chat_ids


def _find_incident_for_point(
    incidents: list[StopListIncident],
    *,
    point_name: str | None,
) -> StopListIncident | None:
    normalized_point_name = _normalize_text(point_name)
    if not normalized_point_name:
        return None

    matches = [
        incident
        for incident in incidents
        if _normalize_text(incident.point_name) == normalized_point_name
    ]
    if not matches:
        return None
    return matches[0]


def _match_incident(
    db,
    *,
    user_id: int,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None,
    reply_to_from_bot: bool | None,
) -> tuple[StopListIncident | None, str | None]:
    incidents = _load_open_incidents(db, user_id=user_id)
    if not incidents:
        return None, None

    if reply_to_message_id:
        direct_matches = [
            incident
            for incident in incidents
            if reply_to_message_id in _incident_message_ids(incident)
            and (not _incident_chat_ids(incident) or chat_id in _incident_chat_ids(incident))
        ]
        if len(direct_matches) == 1:
            return direct_matches[0], "reply_to_alert"

    points = _load_active_points(db, user_id=user_id)
    matched_points = find_delivery_points_for_text(points, text)
    if len(matched_points) == 1:
        incident = _find_incident_for_point(incidents, point_name=matched_points[0].display_name)
        if incident:
            return incident, "point_name"

    chat_points = [
        point
        for point in points
        if getattr(point, "stoplist_report_chat_id", None) == chat_id
    ]
    if len(chat_points) == 1:
        incident = _find_incident_for_point(incidents, point_name=chat_points[0].display_name)
        if incident:
            return incident, "point_chat"

    if reply_to_from_bot is True:
        chat_matches = [
            incident
            for incident in incidents
            if chat_id in _incident_chat_ids(incident)
        ]
        if len(chat_matches) == 1:
            return chat_matches[0], "reply_in_chat"

    chat_matches = [
        incident
        for incident in incidents
        if chat_id in _incident_chat_ids(incident)
    ]
    if len(chat_matches) == 1:
        return chat_matches[0], "chat_context"

    return None, None


def _reaction_not_matched_text() -> str:
    return "Не понял, к какой точке отнести реакцию. Ответьте на сообщение бота или напишите адрес точки."


def _reaction_confirmed_text(status: str, point_name: str) -> str:
    template = _STATUS_RESPONSE_TEXT.get(status) or "Отметил реакцию по стоп-листу для {point_name}."
    return template.format(point_name=point_name)


def apply_stoplist_reaction(
    db,
    *,
    telegram_user_id: int,
    chat_id: int,
    text: str | None,
    observed_at: datetime | None = None,
    message_id: int | None = None,
    reply_to_message_id: int | None = None,
    reply_to_from_bot: bool | None = None,
) -> StopListReactionResult | None:
    manager_status = classify_stoplist_reaction(text)
    if manager_status is None:
        return None

    user = db.query(User).filter(User.telegram_id == telegram_user_id).first()
    if not user:
        return StopListReactionResult(
            handled=True,
            matched=False,
            manager_status=manager_status,
            point_name=None,
            response_text="Сначала нужно открыть активный стоп-лист, чтобы я смог зафиксировать реакцию.",
        )

    incident, matched_by = _match_incident(
        db,
        user_id=int(user.id),
        chat_id=int(chat_id),
        text=str(text or ""),
        reply_to_message_id=reply_to_message_id,
        reply_to_from_bot=reply_to_from_bot,
    )
    if incident is None:
        return StopListReactionResult(
            handled=True,
            matched=False,
            manager_status=manager_status,
            point_name=None,
            response_text=_reaction_not_matched_text(),
        )

    incident.manager_status = manager_status
    incident.manager_note = str(text or "").strip() or None
    incident.manager_updated_at = observed_at or datetime.utcnow()
    incident.manager_updated_by_user_id = int(user.id)
    incident.manager_updated_chat_id = int(chat_id)
    incident.manager_updated_message_id = int(message_id) if message_id is not None else None
    db.flush()

    return StopListReactionResult(
        handled=True,
        matched=True,
        manager_status=manager_status,
        point_name=incident.point_name,
        response_text=_reaction_confirmed_text(manager_status, incident.point_name),
        incident_id=int(incident.id),
        matched_by=matched_by,
    )
