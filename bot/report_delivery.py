REPORT_SCENARIOS = {"reviews_report", "stoplist_report", "blanks_report"}


def is_report_delivery_candidate(result: dict) -> bool:
    return (
        result.get("status") == "completed"
        and result.get("scenario") in REPORT_SCENARIOS
        and bool((result.get("answer") or "").strip())
    )


def trim_telegram_text(text: str, limit: int = 4096) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def build_report_delivery_message(
    *,
    requester_name: str,
    user_message: str,
    answer: str,
) -> str:
    return "\n".join(
        [
            "TaskBridge: отчет от агента",
            f"Запросил: {requester_name}",
            f"Запрос: {user_message.strip()}",
            "",
            answer.strip(),
        ]
    )
