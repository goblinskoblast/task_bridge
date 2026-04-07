from __future__ import annotations

from typing import Any, Dict, Tuple


FAILURE_STATUSES = {
    "failed",
    "error",
    "not_configured",
    "system_not_connected",
    "no_systems_connected",
    "system_not_found",
    "user_not_found",
    "auth_failed",
}

AWAITING_STATUSES = {
    "awaiting_user_input",
    "needs_point",
    "needs_period",
    "needs_input",
}


def derive_response_status(tool_results: Dict[str, dict]) -> str:
    if not tool_results:
        return "completed"

    statuses = []
    for result in tool_results.values():
        if isinstance(result, dict):
            statuses.append(_normalize_status(result.get("status")))

    if any(status in FAILURE_STATUSES for status in statuses):
        return "failed"
    if any(status in AWAITING_STATUSES for status in statuses):
        return "awaiting_user_input"
    return "completed"


def build_debug_artifacts(
    *,
    trace_id: str,
    scenario: str,
    status: str,
    selected_tools: list[str],
    tool_results: Dict[str, dict],
    error_message: str | None = None,
) -> Tuple[dict, str]:
    payload = {
        "trace_id": trace_id,
        "scenario": scenario,
        "status": status,
        "selected_tools": list(selected_tools or []),
        "tools": [],
    }
    if error_message:
        payload["error_message"] = _compact_text(error_message, limit=300)

    for tool_name, result in tool_results.items():
        if not isinstance(result, dict):
            payload["tools"].append(
                {
                    "tool": tool_name,
                    "status": "unknown",
                    "message": _compact_text(str(result), limit=220),
                }
            )
            continue
        payload["tools"].append(_summarize_tool_result(tool_name, result))

    return payload, render_debug_summary(payload)


def render_debug_summary(payload: Dict[str, Any]) -> str:
    lines = [
        f"Trace: {payload.get('trace_id') or '-'}",
        f"Сценарий: {payload.get('scenario') or '-'}",
        f"Статус: {payload.get('status') or '-'}",
    ]

    selected_tools = payload.get("selected_tools") or []
    if selected_tools:
        lines.append(f"Инструменты: {', '.join(str(item) for item in selected_tools)}")

    primary_tool = _choose_primary_tool(payload.get("tools") or [])
    if primary_tool:
        lines.append(f"Источник: {primary_tool.get('tool', '-')}")
        if primary_tool.get("message"):
            lines.append(f"Причина: {primary_tool['message']}")
        if primary_tool.get("stage"):
            lines.append(f"Этап: {primary_tool['stage']}")
        if primary_tool.get("target"):
            lines.append(f"Цель: {primary_tool['target']}")
        if primary_tool.get("url"):
            lines.append(f"URL: {primary_tool['url']}")
        if primary_tool.get("point_selected") is False:
            lines.append("Точка: не подтверждена")
        if primary_tool.get("period_selected") is False:
            lines.append("Период: не подтверждён")
        if primary_tool.get("address_filled") is False:
            lines.append("Адрес: не удалось заполнить")
        if primary_tool.get("matched_point"):
            lines.append(f"Точка в UI: {primary_tool['matched_point']}")
        if primary_tool.get("matched_period"):
            lines.append(f"Период в UI: {primary_tool['matched_period']}")
        if primary_tool.get("products_found") is not None:
            lines.append(f"Найдено позиций: {primary_tool['products_found']}")
    elif payload.get("error_message"):
        lines.append(f"Причина: {payload['error_message']}")

    return "\n".join(lines)


def _summarize_tool_result(tool_name: str, result: Dict[str, Any]) -> dict:
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    item = {
        "tool": tool_name,
        "status": _normalize_status(result.get("status")),
    }

    message = _extract_result_message(result)
    if message:
        item["message"] = message

    stage = diagnostics.get("stage")
    if stage:
        item["stage"] = str(stage)

    url = diagnostics.get("url")
    if url:
        item["url"] = _compact_text(str(url), limit=240)

    for key in ("point_selected", "period_selected", "address_filled", "products_found"):
        if key in diagnostics:
            item[key] = diagnostics[key]

    for key in ("matched_point", "matched_period", "page_excerpt", "point_menu_opener", "point_search_query"):
        value = diagnostics.get(key)
        if value:
            item[key] = _compact_text(str(value), limit=160)

    for key in ("point_candidates", "visible_point_controls", "visible_period_controls"):
        value = diagnostics.get(key)
        if isinstance(value, list) and value:
            item[key] = [_compact_text(str(entry), limit=120) for entry in value[:12]]

    target = _extract_target_label(result)
    if target:
        item["target"] = target

    return item


def _extract_result_message(result: Dict[str, Any]) -> str | None:
    for key in ("message", "error"):
        value = result.get(key)
        if value:
            return _compact_text(str(value), limit=220)

    failed_target = _extract_failed_target(result)
    if failed_target:
        error_text = failed_target.get("error") or failed_target.get("message")
        if error_text:
            return _compact_text(str(error_text), limit=220)

    status = _normalize_status(result.get("status"))
    if status == "system_not_connected":
        return "Система для этого сценария пока не подключена."
    if status == "needs_point":
        return "Для выполнения запроса не хватило точки."
    if status == "no_systems_connected":
        return "У пользователя нет подключённых внешних систем."
    if status == "no_tool_selected":
        return "Для ответа не понадобился внешний инструмент."
    return None


def _extract_target_label(result: Dict[str, Any]) -> str | None:
    failed_target = _extract_failed_target(result)
    if failed_target:
        target = failed_target.get("target")
        if target:
            return _compact_text(str(target), limit=120)
    return None


def _extract_failed_target(result: Dict[str, Any]) -> Dict[str, Any] | None:
    targets = result.get("targets")
    if not isinstance(targets, list):
        return None
    for item in targets:
        if not isinstance(item, dict):
            continue
        item_status = _normalize_status(item.get("status"))
        if item_status in FAILURE_STATUSES:
            return item
    return None


def _choose_primary_tool(items: list[dict]) -> dict | None:
    if not items:
        return None
    for item in items:
        if item.get("status") in FAILURE_STATUSES:
            return item
    for item in items:
        if item.get("status") in AWAITING_STATUSES:
            return item
    return items[0]


def _normalize_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw or "unknown"


def _compact_text(value: str, *, limit: int) -> str:
    normalized = " ".join((value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
