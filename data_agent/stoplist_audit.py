from __future__ import annotations

from datetime import datetime
from typing import Any

from db.models import StopListIncident, StopListIncidentAuditEntry


def append_stoplist_audit_entry(
    db,
    *,
    incident: StopListIncident | None,
    event_type: str,
    source: str,
    summary_text: str,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> StopListIncidentAuditEntry | None:
    if incident is None:
        return None

    entry = StopListIncidentAuditEntry(
        incident_id=int(incident.id),
        user_id=int(incident.user_id),
        point_name=str(incident.point_name),
        event_type=str(event_type).strip(),
        source=str(source).strip(),
        summary_text=str(summary_text).strip()[:2000],
        payload_json=payload if isinstance(payload, dict) else None,
        created_at=created_at or datetime.utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry
