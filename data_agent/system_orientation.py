from __future__ import annotations

import re
from typing import Sequence

from .models import ConnectedSystem
from .system_catalog import (
    build_scan_contract_payload,
    capability_labels,
    entry_surface_label,
    monitor_signal_labels,
    normalize_system_name,
    orientation_summary,
    report_sections,
    resolve_system_descriptor,
    system_family_label,
)

_SYSTEM_SUMMARY_MARKERS = (
    "какие системы",
    "какие у меня системы",
    "покажи системы",
    "подключенные системы",
    "подключённые системы",
    "что у меня подключено",
    "что подключено",
    "по каким системам работаем",
)

_SYSTEM_ORIENTATION_MARKERS = (
    "что умеешь",
    "что можно",
    "как ориентироваться",
    "как устроена",
    "как устроен",
    "какие разделы",
    "куда идти",
    "где искать",
    "что дальше",
    "как смотреть",
    "ориентир",
    "scan",
)

_DETAILED_SCAN_MARKERS = (
    "пошаг",
    "с чего начать",
    "как начать",
    "какой план",
    "план scan",
    "scan план",
    "как проходить",
)

_SYSTEM_HINTS: tuple[tuple[str, str], ...] = (
    ("italian pizza", "italian_pizza"),
    ("italianpizza", "italian_pizza"),
    ("айко", "iiko"),
    ("iiko", "iiko"),
    ("кипер", "keeper"),
    ("rkeeper", "keeper"),
    ("keeper", "keeper"),
    ("rocketdata", "rocketdata"),
    ("рокетдата", "rocketdata"),
    ("1с", "1C"),
    ("1c", "1C"),
    ("crm", "CRM"),
    ("телеграм", "telegram"),
    ("telegram", "telegram"),
    ("макс", "max"),
    ("max", "max"),
)

def wants_system_orientation(message: str) -> bool:
    lowered = _normalize_text(message)
    if not lowered:
        return False
    if any(marker in lowered for marker in _SYSTEM_SUMMARY_MARKERS):
        return True
    requested_names = detect_requested_system_names(message)
    if not requested_names:
        return False
    return any(marker in lowered for marker in _SYSTEM_ORIENTATION_MARKERS)


def detect_requested_system_names(message: str) -> list[str]:
    lowered = _normalize_text(message)
    if not lowered:
        return []

    names: list[str] = []
    for marker, system_name in _SYSTEM_HINTS:
        if marker in lowered and system_name not in names:
            names.append(system_name)
    return names


def build_orientation_answer(message: str, systems: Sequence[ConnectedSystem]) -> str:
    requested_names = detect_requested_system_names(message)
    connected_map = {normalize_system_name(item.system_name): item for item in systems}
    detailed_scan = _wants_detailed_scan_plan(message)

    if requested_names:
        blocks: list[str] = []
        requested_connected = [name for name in requested_names if name in connected_map]
        requested_missing = [name for name in requested_names if name not in connected_map]

        if requested_connected:
            blocks.append("По подключённым системам ориентир такой:\n")
            blocks.extend(
                _render_system_block(
                    index,
                    system_name=name,
                    connected_system=connected_map[name],
                    connected=True,
                    detailed_scan=detailed_scan,
                )
                for index, name in enumerate(requested_connected, start=1)
            )

        if requested_missing:
            if blocks:
                blocks.append("")
            blocks.append(f"{_missing_systems_heading(len(requested_missing))}, но базовый ориентир уже такой:\n")
            blocks.extend(
                _render_system_block(
                    index,
                    system_name=name,
                    connected_system=None,
                    connected=False,
                    detailed_scan=detailed_scan,
                )
                for index, name in enumerate(requested_missing, start=1)
            )

        if not requested_connected and systems:
            connected_titles = ", ".join(_system_title(item) for item in systems)
            blocks.append("")
            blocks.append(f"Сейчас из подключённых вижу: {connected_titles}.")

        return "\n".join(part for part in blocks if part)

    if not systems:
        return (
            "Подключённых систем пока нет.\n\n"
            "Сейчас боевой контур уже есть для Italian Pizza. Следом готовим iiko, keeper и новые клиентские каналы.\n"
            "Когда подключите систему, я смогу сразу подсказать, где искать точки, отчёты и что дальше ставить на мониторинг."
        )

    lines = [f"{_connected_systems_heading(len(systems))}.\n"]
    lines.extend(
        _render_system_block(
            index,
            system_name=item.system_name,
            connected_system=item,
            connected=True,
            detailed_scan=detailed_scan,
        )
        for index, item in enumerate(systems, start=1)
    )
    lines.append("")
    lines.append("Если нужно, могу отдельно развернуть ориентир по любой конкретной системе.")
    return "\n".join(lines)


def _render_system_block(
    index: int,
    *,
    system_name: str,
    connected_system: ConnectedSystem | None,
    connected: bool,
    detailed_scan: bool,
) -> str:
    descriptor = resolve_system_descriptor(system_name=system_name, url=getattr(connected_system, "url", None))
    title = _system_title(connected_system) if connected_system else descriptor.title
    family = system_family_label(getattr(connected_system, "system_family", None) or descriptor.family)
    surface = entry_surface_label(getattr(connected_system, "entry_surface", None) or descriptor.entry_surface)
    capabilities = getattr(connected_system, "capability_labels", None) or capability_labels(descriptor)
    orientation = getattr(connected_system, "orientation_summary", None) or orientation_summary(descriptor)
    next_step = getattr(connected_system, "next_step_hint", None) or descriptor.next_step_hint
    contract = getattr(connected_system, "scan_contract", None)
    fallback_contract = build_scan_contract_payload(descriptor)
    stage_label = str(getattr(contract, "stage_label", None) or fallback_contract.get("stage_label") or "")
    auth_label = str(getattr(contract, "auth_mode_label", None) or fallback_contract.get("auth_mode_label") or "")
    primary_entities = list(getattr(contract, "primary_entities", None) or fallback_contract.get("primary_entities") or ())
    report_entries = list(getattr(contract, "report_sections", None) or report_sections(descriptor))
    monitor_targets = list(getattr(contract, "monitor_signals", None) or monitor_signal_labels(descriptor))
    reliability_policy = list(getattr(contract, "reliability_policy", None) or fallback_contract.get("reliability_policy") or ())
    capability_matrix = list(getattr(contract, "capability_matrix", None) or fallback_contract.get("capability_matrix") or ())
    scan_steps = list(getattr(contract, "scan_steps", None) or fallback_contract.get("scan_steps") or ())
    starter_step = str(getattr(contract, "starter_step", None) or fallback_contract.get("starter_step") or "")
    progress = getattr(connected_system, "scan_progress", None)
    progress_status = str(getattr(progress, "status_label", None) or "").strip()
    current_step_label = str(getattr(progress, "current_step_label", None) or "").strip()
    next_step_label = str(getattr(progress, "next_step_label", None) or "").strip()
    discovered_entities = list(getattr(progress, "discovered_entities", None) or ())
    discovered_sections = list(getattr(progress, "discovered_sections", None) or ())
    evidence_summary = str(getattr(progress, "evidence_summary", None) or "").strip()
    blocked_reason = str(getattr(progress, "blocked_reason", None) or "").strip()
    if not progress_status and starter_step:
        progress_status = "ещё не начинали"
    if not current_step_label and not next_step_label and starter_step:
        next_step_label = starter_step

    lines = [f"{index}. {title} — {family}"]
    if not connected:
        lines.append("не подключена")
    if stage_label:
        lines.append(f"стадия: {stage_label}")
    lines.append(f"вход: {surface}")
    if auth_label:
        lines.append(f"авторизация: {auth_label}")
    if primary_entities:
        lines.append(f"сущности: {', '.join(primary_entities)}")
    if capabilities:
        lines.append(f"можем: {', '.join(capabilities)}")
    if capability_matrix:
        readiness = "; ".join(
            f"{item.get('label', item.get('capability', 'capability'))} — {item.get('stage_label', item.get('stage', 'неизвестно'))}"
            for item in capability_matrix
        )
        lines.append(f"готовность: {readiness}")
    if report_entries:
        lines.append(f"разделы: {', '.join(report_entries)}")
    if monitor_targets:
        lines.append(f"сигналы: {', '.join(monitor_targets)}")
    if reliability_policy:
        lines.append(f"надёжность: {'; '.join(reliability_policy)}")
    if orientation:
        lines.append(f"ориентир: {orientation}")
    if starter_step:
        lines.append(f"старт: {starter_step}")
    if progress_status:
        progress_parts = [progress_status]
        if current_step_label:
            progress_parts.append(f"текущий шаг: {current_step_label}")
        elif next_step_label:
            progress_parts.append(f"следующий шаг: {next_step_label}")
        lines.append("прогресс: " + "; ".join(progress_parts))
    if discovered_entities:
        lines.append(f"найденные сущности: {', '.join(discovered_entities)}")
    if discovered_sections:
        lines.append(f"найденные разделы: {', '.join(discovered_sections)}")
    if evidence_summary:
        lines.append(f"что уже подтвердили: {evidence_summary}")
    if blocked_reason:
        lines.append(f"где упёрлись: {blocked_reason}")
    if detailed_scan and scan_steps:
        lines.append("scan-план:")
        for step_index, step in enumerate(scan_steps, start=1):
            label = str(step.get("label") or f"Шаг {step_index}")
            objective = str(step.get("objective") or "").strip()
            automation_label = str(step.get("automation_label") or step.get("automation_stage") or "").strip()
            evidence_hint = str(step.get("evidence_hint") or "").strip()
            parts = [label]
            if automation_label:
                parts.append(automation_label)
            if objective:
                parts.append(objective)
            if evidence_hint:
                parts.append(f"проверка: {evidence_hint}")
            lines.append(f"{step_index}. " + " — ".join(parts))
    if next_step:
        lines.append(f"дальше: {next_step}")
    return "\n".join(lines)


def _system_title(system: ConnectedSystem | None) -> str:
    if not system:
        return "System"
    return str(system.system_title or system.system_name or "System")


def _connected_systems_heading(count: int) -> str:
    if count == 1:
        return "Сейчас вижу 1 подключённую систему"
    return f"Сейчас вижу {count} подключённые системы"


def _missing_systems_heading(count: int) -> str:
    if count == 1:
        return "Эта система у вас пока не подключена"
    return "Эти системы у вас пока не подключены"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _wants_detailed_scan_plan(message: str) -> bool:
    lowered = _normalize_text(message)
    return any(marker in lowered for marker in _DETAILED_SCAN_MARKERS)
