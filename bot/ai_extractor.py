from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from dateutil import parser as date_parser

from bot.ai_provider import get_ai_provider
from config import OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, TIMEZONE

logger = logging.getLogger(__name__)


UNIFIED_TASK_SYSTEM_PROMPT = """
You extract actionable tasks from work communications.

Source channel: {source}
Current date/time: {current_datetime}

You receive a normalized communication package. It may contain:
- current message or email body
- subject
- recent thread context
- attachment text
- participant hints

Your job is to decide whether the package contains a real actionable task.
If yes, return exactly one primary task.

Core rules:
- Use context to resolve references like "it", "this", "as discussed", "then do it by Saturday".
- Treat imperative requests and operational instructions as tasks: examples include "пришлите", "отправьте", "подготовьте", "проверьте", "согласуйте", "fill", "send", "prepare", "review".
- Treat meeting and call invitations as tasks too. If the communication asks someone to attend a meeting, join a call, be on a demo, or connect at a specific time, extract it as a task.
- A task may be indirect. If the sender expects a concrete result, artifact, answer, file, update, approval, or action, it is a task candidate.
- For Telegram, the current message must trigger the task. Older context may complete the details but should not create a task on its own.
- For Email, use subject, body, quoted thread, and attachment text together.
- Ignore pure discussion, jokes, newsletters, ads, receipts, and service notifications without an expected action.
- Build a short clean title. Remove greetings, direct addresses, filler, and repeated deadline wording when possible.
- Preserve meeting metadata in description when present: address, meeting place, floor/room, call link, dial-in details.
- description should keep the useful actionable details in natural language.
- assignee_usernames must be an array without @.
- If a person is mentioned by name but no Telegram username is known, return the plain name in assignee_usernames.
- Convert relative deadlines into absolute format YYYY-MM-DD HH:MM:SS when possible, otherwise null.
- Priority mapping: urgent/high for срочно, asap, urgent, critical; low for when you have time, не срочно; otherwise normal.

Return ONLY JSON:
{{
  "has_task": true,
  "task": {{
    "title": "short task title",
    "description": "clear task description",
    "assignee_usernames": ["user1"],
    "due_date": "YYYY-MM-DD HH:MM:SS or null",
    "priority": "low/normal/high/urgent"
  }}
}}

If there is no task:
{{
  "has_task": false,
  "task": null
}}
""".strip()


RUS_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "среду": 2,
    "четверг": 3,
    "пятница": 4,
    "пятницу": 4,
    "суббота": 5,
    "субботу": 5,
    "воскресенье": 6,
}

RUS_NUMBER_WORDS = {
    "один": 1,
    "одну": 1,
    "одного": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "трёх": 3,
    "четыре": 4,
    "четырех": 4,
    "четырёх": 4,
    "пять": 5,
    "пяти": 5,
    "шесть": 6,
    "шести": 6,
    "семь": 7,
    "семи": 7,
}

RUS_MONTHS = {
    "январь": 1,
    "января": 1,
    "февраль": 2,
    "февраля": 2,
    "март": 3,
    "марта": 3,
    "апрель": 4,
    "апреля": 4,
    "май": 5,
    "мая": 5,
    "июнь": 6,
    "июня": 6,
    "июль": 7,
    "июля": 7,
    "август": 8,
    "августа": 8,
    "сентябрь": 9,
    "сентября": 9,
    "октябрь": 10,
    "октября": 10,
    "ноябрь": 11,
    "ноября": 11,
    "декабрь": 12,
    "декабря": 12,
}

IMPERATIVE_MARKERS = [
    "тебе нужно",
    "вам нужно",
    "нужно",
    "надо",
    "необходимо",
    "прошу",
    "сделай",
    "сделайте",
    "подготовь",
    "подготовьте",
    "напиши",
    "напишите",
    "продумай",
    "продумайте",
    "пришли",
    "пришлите",
    "отправь",
    "отправьте",
    "согласуй",
    "согласуйте",
    "проверь",
    "проверьте",
    "заполни",
    "заполните",
    "создай",
    "создайте",
    "собери",
    "соберите",
    "обнови",
    "обновите",
    "подумай",
    "посмотри",
    "посмотрите",
    "ожидаю",
    "жду",
    "please",
    "need",
    "must",
    "should",
    "prepare",
    "send",
    "write",
    "review",
    "check",
    "fill",
    "update",
]

IMPERATIVE_VERB_FORMS = {
    "пришлите": "Прислать",
    "пришли": "Прислать",
    "отправьте": "Отправить",
    "отправь": "Отправить",
    "подготовьте": "Подготовить",
    "подготовь": "Подготовить",
    "напишите": "Подготовить",
    "напиши": "Подготовить",
    "сделайте": "Сделать",
    "сделай": "Сделать",
    "проверьте": "Проверить",
    "проверь": "Проверить",
    "согласуйте": "Согласовать",
    "согласуй": "Согласовать",
    "заполните": "Заполнить",
    "заполни": "Заполнить",
    "создайте": "Создать",
    "создай": "Создать",
    "соберите": "Собрать",
    "собери": "Собрать",
    "обновите": "Обновить",
    "обнови": "Обновить",
    "продумайте": "Продумать",
    "продумай": "Продумать",
    "посмотрите": "Проверить",
    "посмотри": "Проверить",
}

NOISE_MARKERS = [
    "newsletter",
    "unsubscribe",
    "promo",
    "receipt",
    "скидка",
    "акция",
    "промокод",
    "чек",
]

ERROR_SUBJECT_MARKERS = [
    "обнаружены ошибки",
    "ошибка",
    "error",
    "invalid",
    "некорректный формат",
]

MEETING_MARKERS = [
    "встреча",
    "встретимся",
    "встретиться",
    "созвон",
    "созвониться",
    "колл",
    "звонок",
    "видеозвонок",
    "call",
    "meeting",
    "zoom",
    "google meet",
    "meet.google",
    "teams.microsoft",
    "webex",
    "demo",
]


def get_current_datetime() -> str:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


def _build_extraction_prompt(
    source: str,
    current_text: str,
    context_messages: Optional[List[Dict[str, Any]]] = None,
    subject: str = "",
    body_text: str = "",
    attachments_text: str = "",
) -> str:
    lines: List[str] = [f"SOURCE: {source}"]

    if source == "telegram":
        lines.extend(["CURRENT MESSAGE:", (current_text or "").strip()])
        if context_messages:
            lines.extend(["", "RECENT CONTEXT (oldest to newest):"])
            for item in context_messages:
                body = (item.get("text") or "").strip()
                if not body:
                    continue
                sender = item.get("sender") or "unknown"
                sent_at = item.get("date") or ""
                lines.append(f"[{sent_at}] {sender}: {body}".strip())
    else:
        lines.extend([
            "EMAIL SUBJECT:",
            (subject or "").strip(),
            "",
            "EMAIL BODY:",
            (body_text or current_text or "").strip(),
        ])
        if context_messages:
            lines.extend(["", "EMAIL THREAD CONTEXT:"])
            for item in context_messages:
                body = (item.get("text") or "").strip()
                if not body:
                    continue
                sender = item.get("sender") or "unknown"
                sent_at = item.get("date") or ""
                lines.append(f"[{sent_at}] {sender}: {body}".strip())
        if attachments_text:
            lines.extend(["", "ATTACHMENT TEXT:", attachments_text.strip()])

    return "\n".join(lines).strip()


def _extract_marked_section(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}:\s*(.+?)(?:\n[A-Z ]+:|$)", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_email_payload(text: str) -> Dict[str, str]:
    subject = _extract_marked_section(text, "EMAIL SUBJECT")
    body = _extract_marked_section(text, "EMAIL BODY")
    attachments = _extract_marked_section(text, "ATTACHMENT TEXT") or _extract_marked_section(text, "ATTACHMENTS")
    if not body:
        body = text.strip()
    return {
        "subject": subject,
        "body": body,
        "attachments_text": attachments,
    }


def _clean_action_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"^(привет|добрый день|здравствуй|здравствуйте|hello|hi)\b[!,.:\s-]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[А-ЯA-ZЁ][а-яa-zё-]+,\s+", "", cleaned)
    cleaned = re.sub(r"^[А-ЯA-ZЁ][а-яa-zё-]+\s+(?=(нужно|надо|необходимо|прошу|можешь|надо бы)\b)", "", cleaned)
    cleaned = re.sub(r"^(тебе|вам)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(нужно|надо|необходимо|прошу)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(please)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .,:;-")


def _clean_title_candidate(text: str) -> str:
    cleaned = _clean_action_text(text)
    cleaned = re.sub(r"\s+(до|к|через)\s+.+$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(сегодня|завтра)\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(в\s+ворде|в\s+excel|в\s+pdf)\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" .,:;-")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned[:120]


def _contains_deadline_signal(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False

    deadline_markers = [
        "срок",
        "дедлайн",
        "deadline",
        "до ",
        "к ",
        "завтра",
        "сегодня",
        "через ",
        "на этой неделе",
        "до конца",
        "by ",
        "until ",
        "before ",
    ]
    if any(marker in lowered for marker in deadline_markers):
        return True

    if re.search(r"(?:с|from)\s*\d{1,2}(?:[./-]\d{1,2}|\s+[а-яё]+).{0,20}(?:по|до|to|-)\s*\d{1,2}(?:[./-]\d{1,2}|\s+[а-яё]+)", lowered):
        return True

    if re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", lowered):
        return True
    if re.search(r"\b\d{1,2}\s+(январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])\b", lowered):
        return True
    if any(word in lowered for word in RUS_WEEKDAYS):
        return True

    return False


def _coerce_future_if_missing_year(target: datetime, now: datetime, has_explicit_year: bool) -> datetime:
    if has_explicit_year:
        return target

    if target < now - timedelta(days=1):
        try:
            return target.replace(year=target.year + 1)
        except ValueError:
            return target + timedelta(days=365)

    return target


def _extract_date_range_due_date(text: str, now: datetime, tz) -> Optional[datetime]:
    lowered = (text or "").lower()
    if not lowered:
        return None

    numeric_range = re.search(
        r"(?:с|from)\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*(?:по|до|to|-)\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?",
        lowered,
    )
    if numeric_range:
        end_day = int(numeric_range.group(4))
        end_month = int(numeric_range.group(5))
        end_year_raw = numeric_range.group(6) or numeric_range.group(3)
        end_year = int(end_year_raw) if end_year_raw else now.year
        if end_year < 100:
            end_year += 2000
        target = tz.localize(datetime(end_year, end_month, end_day, 18, 0, 0))
        return _coerce_future_if_missing_year(target, now, bool(end_year_raw))

    text_range = re.search(
        r"(?:с|from)\s*(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?\s*(?:по|до|to|-)\s*(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?",
        lowered,
    )
    if text_range:
        end_day = int(text_range.group(4))
        end_month = RUS_MONTHS.get(text_range.group(5))
        if end_month:
            end_year_raw = text_range.group(6) or text_range.group(3)
            end_year = int(end_year_raw) if end_year_raw else now.year
            target = tz.localize(datetime(end_year, end_month, end_day, 18, 0, 0))
            return _coerce_future_if_missing_year(target, now, bool(end_year_raw))

    return None


def _extract_due_date(text: str) -> Optional[datetime]:
    if not text:
        return None

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    text_lower = text.lower()

    range_due_date = _extract_date_range_due_date(text, now, tz)
    if range_due_date:
        return range_due_date

    explicit_datetime_patterns = [
        r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\s+в\s+\d{1,2}:\d{2}\b",
        r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\s+\d{1,2}:\d{2}\b",
        r"\b\d{1,2}\.\d{1,2}\s+в\s+\d{1,2}:\d{2}\b",
        r"\b\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}\b",
    ]
    for pattern in explicit_datetime_patterns:
        match = re.search(pattern, text_lower)
        if not match:
            continue
        fragment = match.group(0).replace(" в ", " ")
        try:
            parsed = date_parser.parse(
                fragment,
                dayfirst=True,
                fuzzy=True,
                default=now.replace(hour=18, minute=0, second=0, microsecond=0),
            )
            if parsed.tzinfo is None:
                parsed = tz.localize(parsed)
            has_explicit_year = bool(re.search(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b", fragment))
            return _coerce_future_if_missing_year(parsed, now, has_explicit_year)
        except Exception:
            continue

    if _contains_deadline_signal(text_lower) or _contains_meeting_signal(text_lower):
        time_only_match = re.search(r"\b(\d{1,2}):(\d{2})\b", text_lower)
        if time_only_match:
            return now.replace(
                hour=int(time_only_match.group(1)),
                minute=int(time_only_match.group(2)),
                second=0,
                microsecond=0,
            )

    if "сегодня" in text_lower:
        time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", text_lower)
        if time_match:
            return now.replace(hour=int(time_match.group(1)), minute=int(time_match.group(2)), second=0, microsecond=0)
        return now.replace(hour=18, minute=0, second=0, microsecond=0)

    if "завтра" in text_lower:
        target = now + timedelta(days=1)
        time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", text_lower)
        if time_match:
            return target.replace(hour=int(time_match.group(1)), minute=int(time_match.group(2)), second=0, microsecond=0)
        return target.replace(hour=18, minute=0, second=0, microsecond=0)

    days_match = re.search(r"через\s+(\d+)\s+(дн|дня|дней)", text_lower)
    if days_match:
        target = now + timedelta(days=int(days_match.group(1)))
        return target.replace(hour=18, minute=0, second=0, microsecond=0)

    words_match = re.search(
        r"(?:через|за|в течение|хватит)\s+(один|одну|одного|два|две|двух|три|трех|трёх|четыре|четырех|четырёх|пять|пяти|шесть|шести|семь|семи)\s+(дн|дня|дней)",
        text_lower,
    )
    if words_match:
        days = RUS_NUMBER_WORDS.get(words_match.group(1))
        if days:
            target = now + timedelta(days=days)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

    numeric_days_match = re.search(r"(?:за|в течение|хватит)\s+(\d+)\s*[- ]?х?\s*(дн|дня|дней)", text_lower)
    if numeric_days_match:
        target = now + timedelta(days=int(numeric_days_match.group(1)))
        return target.replace(hour=18, minute=0, second=0, microsecond=0)

    for word, weekday in RUS_WEEKDAYS.items():
        if re.search(rf"(до|к)\s+(этой\s+|этому\s+)?{word}\b", text_lower):
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = now + timedelta(days=days_ahead)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

    return None


def _infer_priority(text: str) -> str:
    text_lower = (text or "").lower()
    if any(marker in text_lower for marker in ["критично", "critical"]):
        return "urgent"
    if any(marker in text_lower for marker in ["срочно", "asap", "urgent"]):
        return "high"
    if "не срочно" in text_lower or "when you have time" in text_lower:
        return "low"
    return "normal"


def _extract_mentions(text: str) -> List[str]:
    return [item.lstrip("@") for item in re.findall(r"@[A-Za-z0-9_]+", text or "")]


def _contains_imperative_signal(text: str) -> bool:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in IMPERATIVE_MARKERS):
        return True
    if re.search(r"\b(пришлите|отправьте|подготовьте|согласуйте|проверьте|заполните|обновите)\b", lowered):
        return True
    if re.search(r"\b(please|send|prepare|review|check|fill|update)\b", lowered):
        return True
    return False


def _contains_meeting_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in MEETING_MARKERS)


def _is_noise(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def _build_title_from_imperative(text: str) -> str:
    cleaned = _clean_action_text(text)
    lowered = cleaned.lower()
    for source_verb, normalized in IMPERATIVE_VERB_FORMS.items():
        if lowered.startswith(source_verb):
            tail = cleaned[len(source_verb):].strip(" .,:;-")
            title = f"{normalized} {tail}".strip()
            return _clean_title_candidate(title)
    return _clean_title_candidate(cleaned)


def _extract_meeting_metadata(text: str) -> Dict[str, Optional[str]]:
    raw_text = (text or "").strip()
    lowered = raw_text.lower()

    url_match = re.search(r"https?://\S+", raw_text)
    location_match = re.search(
        r"(?:адрес|локация|место|офис|по адресу|в офисе|в переговорке|room|address)\s*[:\-]?\s*([^\n]+)",
        raw_text,
        flags=re.IGNORECASE,
    )
    time_match = re.search(r"\b\d{1,2}:\d{2}\b", raw_text)

    title = None
    if _contains_meeting_signal(lowered):
        if any(marker in lowered for marker in ["созвон", "звонок", "call", "meet.google", "zoom", "teams.microsoft", "webex"]):
            title = "Подключиться к созвону"
        else:
            title = "Принять участие во встрече"

    details: List[str] = []
    if url_match:
        details.append(f"Ссылка: {url_match.group(0)}")
    if location_match:
        details.append(f"Адрес: {location_match.group(1).strip()}")
    if time_match:
        details.append(f"Время: {time_match.group(0)}")

    return {
        "title": title,
        "details": "\n".join(details) if details else None,
    }


def _select_best_email_trigger_text(subject: str, body_text: str) -> str:
    subject = (subject or "").strip()
    body_text = (body_text or "").strip()

    body_lines = [line.strip(" -\t") for line in re.split(r"[\r\n]+", body_text) if line.strip()]
    body_sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", body_text) if item.strip()]

    candidates = body_lines + body_sentences
    for candidate in candidates:
        if _contains_imperative_signal(candidate):
            return candidate

    if not any(marker in subject.lower() for marker in ERROR_SUBJECT_MARKERS) and subject:
        return subject

    return body_text or subject


def _build_fallback_task(
    source: str,
    current_text: str,
    context_messages: Optional[List[Dict[str, Any]]] = None,
    subject: str = "",
    body_text: str = "",
    attachments_text: str = "",
) -> Optional[Dict[str, Any]]:
    current_text = (current_text or "").strip()
    subject = (subject or "").strip()
    body_text = (body_text or current_text).strip()
    attachments_text = (attachments_text or "").strip()

    trigger_text = current_text if source == "telegram" else _select_best_email_trigger_text(subject, body_text)
    context_text = "\n".join((item.get("text") or "").strip() for item in (context_messages or []) if (item.get("text") or "").strip())
    combined_text = "\n".join(part for part in [subject, body_text, context_text, attachments_text] if part).strip()

    if not combined_text or _is_noise(combined_text):
        return None

    if not _contains_imperative_signal(trigger_text):
        if source == "email" and not (_contains_imperative_signal(combined_text) or _contains_meeting_signal(combined_text)):
            return None
        if source == "telegram" and not _contains_meeting_signal(combined_text):
            return None

    meeting_meta = _extract_meeting_metadata(combined_text)

    title = (
        subject
        if source == "email"
        and subject
        and len(subject) <= 120
        and not any(marker in subject.lower() for marker in ERROR_SUBJECT_MARKERS)
        else _build_title_from_imperative(trigger_text)
    )
    if not title and meeting_meta["title"]:
        title = meeting_meta["title"]
    if not title:
        title = _build_title_from_imperative(body_text)
    if not title:
        title = "Задача"

    description_parts: List[str] = []
    if source == "email":
        if subject:
            description_parts.append(f"Тема: {subject}")
        if body_text:
            description_parts.append(body_text)
        if attachments_text:
            description_parts.append(attachments_text)
    else:
        description_parts.append(current_text)
        if context_text:
            description_parts.append(f"Контекст: {context_text}")

    if meeting_meta["details"]:
        description_parts.append(meeting_meta["details"])

    description = "\n\n".join(part.strip() for part in description_parts if part.strip()) or title
    due_date = _extract_due_date(combined_text)
    assignee_usernames = _extract_mentions(trigger_text)

    return {
        "has_task": True,
        "task": {
            "title": title,
            "description": description,
            "assignee_usernames": assignee_usernames,
            "due_date": due_date.strftime("%Y-%m-%d %H:%M:%S") if due_date else None,
            "priority": _infer_priority(combined_text),
        },
    }


def _normalize_task_result(result: Optional[Dict[str, Any]], fallback_text: str = "") -> Optional[Dict[str, Any]]:
    if not result or not isinstance(result, dict) or "has_task" not in result:
        logger.error("Invalid AI response format: %s", result)
        return None

    if not result.get("has_task", False):
        return {"has_task": False, "task": None}

    task = result.get("task") or {}
    title = (task.get("title") or "").strip()
    description = (task.get("description") or "").strip()

    if not title and description:
        title = _clean_title_candidate(description) or description[:100]
    if not description and title:
        description = title

    task["title"] = title or "Задача"
    task["description"] = description or task["title"]

    if not isinstance(task.get("assignee_usernames"), list):
        single_assignee = task.get("assignee_username")
        task["assignee_usernames"] = [single_assignee] if single_assignee else []

    combined_text = f"{task.get('title', '')}\n{task.get('description', '')}\n{fallback_text}".strip()
    deterministic_due_date = _extract_due_date(combined_text)

    if deterministic_due_date:
        task["due_date_parsed"] = deterministic_due_date
        task["due_date"] = deterministic_due_date.strftime("%Y-%m-%d %H:%M:%S")
    elif task.get("due_date") and _contains_deadline_signal(combined_text):
        try:
            task["due_date_parsed"] = date_parser.parse(task["due_date"])
        except Exception as exc:
            logger.warning("Failed to parse due_date %s: %s", task.get("due_date"), exc)
            task["due_date_parsed"] = None
    else:
        task["due_date_parsed"] = None
        task["due_date"] = None

    if not task.get("priority"):
        task["priority"] = _infer_priority(f"{task.get('title', '')}\n{task.get('description', '')}\n{fallback_text}")

    result["task"] = task
    return result


async def _analyze_with_unified_prompt(
    source: str,
    current_text: str,
    context_messages: Optional[List[Dict[str, Any]]] = None,
    subject: str = "",
    body_text: str = "",
    attachments_text: str = "",
) -> Optional[Dict[str, Any]]:
    if not (current_text or body_text or subject):
        return None

    current_dt = get_current_datetime()
    system_prompt = UNIFIED_TASK_SYSTEM_PROMPT.format(source=source, current_datetime=current_dt)
    user_prompt = _build_extraction_prompt(
        source=source,
        current_text=current_text,
        context_messages=context_messages,
        subject=subject,
        body_text=body_text,
        attachments_text=attachments_text,
    )

    provider = get_ai_provider()
    logger.info("Calling AI provider for %s extraction", source)
    result = await provider.analyze_message(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=OPENAI_TEMPERATURE,
        max_tokens=OPENAI_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    logger.info("AI provider response for %s: %s", source, result)
    return _normalize_task_result(result, fallback_text=user_prompt)


async def analyze_message_with_ai(
    text: str,
    context_messages: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not text or not text.strip():
        return None

    try:
        return await _analyze_with_unified_prompt(
            source="telegram",
            current_text=text,
            context_messages=context_messages,
        )
    except Exception as exc:
        logger.error("Error in Telegram AI analysis: %s", exc, exc_info=True)
        return None


async def analyze_email_with_ai(text: str) -> Optional[Dict[str, Any]]:
    if not text or not text.strip():
        return None

    email_payload = _parse_email_payload(text)

    try:
        normalized = await _analyze_with_unified_prompt(
            source="email",
            current_text=email_payload["body"],
            subject=email_payload["subject"],
            body_text=email_payload["body"],
            attachments_text=email_payload["attachments_text"],
        )
        if normalized and normalized.get("has_task"):
            return normalized
    except Exception as exc:
        logger.error("Error in email AI analysis: %s", exc, exc_info=True)

    fallback = _build_fallback_task(
        source="email",
        current_text=email_payload["body"],
        subject=email_payload["subject"],
        body_text=email_payload["body"],
        attachments_text=email_payload["attachments_text"],
    )
    if fallback:
        logger.info("Email fallback extractor found task: %s", fallback)
        return _normalize_task_result(fallback, fallback_text=text)

    return {"has_task": False, "task": None}


def extract_task_simple(text: str) -> bool:
    if not text:
        return False
    return _contains_imperative_signal(text) or bool(_extract_mentions(text))


async def analyze_message(
    text: str,
    use_ai: bool = True,
    context_messages: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    if use_ai:
        try:
            result = await analyze_message_with_ai(text, context_messages=context_messages)
            if result is not None:
                if result.get("has_task"):
                    return result
                fallback = _build_fallback_task(
                    source="telegram",
                    current_text=text,
                    context_messages=context_messages,
                )
                if fallback:
                    logger.info("Telegram fallback extractor found task: %s", fallback)
                    return _normalize_task_result(fallback, fallback_text=text)
                return result
            logger.warning("AI returned None, using deterministic fallback")
        except Exception as exc:
            logger.error("AI analysis failed, using deterministic fallback: %s", exc)

    fallback = _build_fallback_task(
        source="telegram",
        current_text=text,
        context_messages=context_messages,
    )
    if fallback:
        return _normalize_task_result(fallback, fallback_text=text)

    return {
        "has_task": False,
        "task": None,
    }
