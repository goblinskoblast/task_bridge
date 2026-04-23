from __future__ import annotations

from dataclasses import dataclass
from html import escape

from db.models import StopListIncident


@dataclass(frozen=True)
class StopListMonitorCard:
    event_title: str
    plain_text: str
    html_text: str


def _headline_for_incident(
    incident: StopListIncident | None,
    *,
    changed: bool,
) -> tuple[str, str]:
    if incident is not None:
        lifecycle = str(incident.lifecycle_state or "").strip().lower()
        if lifecycle == "new":
            return "Новый стоп-лист", "новый"
        if lifecycle == "ongoing":
            return "Стоп-лист продолжается", "продолжается"
        if lifecycle == "resolved":
            return "Стоп-лист нормализовался", "нормализовался"
    if changed:
        return "Стоп-лист изменился", "изменился"
    return "Стоп-лист по расписанию", "по расписанию"


def build_stoplist_monitor_card(
    *,
    point_name: str,
    report_text: str,
    incident: StopListIncident | None,
    changed: bool,
    now=None,
) -> StopListMonitorCard:
    del now

    headline, _ = _headline_for_incident(incident, changed=changed)
    normalized_report = (report_text or "").strip()

    plain_lines = [headline]
    html_lines = [escape(headline)]

    if normalized_report:
        plain_lines.extend(["", normalized_report])
        html_lines.extend(["", escape(normalized_report)])

    return StopListMonitorCard(
        event_title=f"{headline}: {point_name}",
        plain_text="\n".join(plain_lines).strip(),
        html_text="\n".join(html_lines).strip(),
    )
