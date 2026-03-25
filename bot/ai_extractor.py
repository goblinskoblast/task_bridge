import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from dateutil import parser as date_parser

from bot.ai_provider import get_ai_provider
from config import OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, TIMEZONE

logger = logging.getLogger(__name__)


CHAT_CONTEXT_SYSTEM_PROMPT = """
You extract actionable tasks from Telegram chats.

The chat may be in Russian or English.
Current date/time: {current_datetime}

Decide whether the CURRENT message, together with RECENT CHAT CONTEXT, contains a real task.
If yes, extract one primary task.

Rules:
- Use recent context to resolve references like "this", "that", "it", "as discussed", "then do it by Saturday".
- A task may be spread across several messages. Context may define subject, assignee, deadline, or priority.
- The CURRENT message is the trigger. Do not create a task only from old context if the current message is unrelated.
- Catch indirect tasks too: polite requests, reminders, commitments, hints, agreements, and veiled formulations.
- Do not mark pure discussion, jokes, status updates, or generic questions without action as tasks.
- Build a short clean title. Remove greetings, filler words, direct addresses, and duplicate deadline phrasing when possible.
- description should keep the useful task details in natural language.
- assignee_usernames must be an array without @.
- If a person is mentioned by name but no Telegram username is known, return the plain name in assignee_usernames.
- Convert relative deadlines into absolute format YYYY-MM-DD HH:MM:SS when possible, otherwise null.
- Priority mapping: urgent/high for срочно, asap, urgent, critical; low for when you have time, не срочно; otherwise normal.

Return ONLY JSON:
{
  "has_task": true,
  "task": {
    "title": "short task title",
    "description": "clear task description",
    "assignee_usernames": ["user1"],
    "due_date": "YYYY-MM-DD HH:MM:SS or null",
    "priority": "low/normal/high/urgent"
  }
}

If there is no task:
{
  "has_task": false,
  "task": null
}
""".strip()


EMAIL_SYSTEM_PROMPT = """
You extract actionable tasks from business emails.

The email may be in Russian or English.
Current date/time: {current_datetime}

Rules:
- Detect direct and indirect requests, reminders, commitments, follow-ups, and expected deliverables.
- Use quoted email thread fragments as context when they clarify who must do what and by when.
- Treat polite business wording as a task when there is an expected result: "please prepare", "could you send", "I need by Friday", "waiting for", "вам нужно", "тебе нужно", "прошу направить", "ожидаю", "нужно подготовить", "пришли мне", "сделай".
- If the body contains a question that already encodes a deadline or expectation, treat it as a task, not as a casual question.
- Ignore ads, promo, receipts, newsletters, and service notifications unless they contain a concrete task.
- Return one primary task only.
- Build a short clean title and a fuller description.
- assignee_usernames should normally be an empty array for email flow.
- Convert relative deadlines into absolute format YYYY-MM-DD HH:MM:SS when possible, otherwise null.
- Priority mapping: urgent/high for срочно, asap, urgent, critical; low for when you have time, не срочно; otherwise normal.

Return ONLY JSON in the same schema as chat extraction.
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

EMAIL_TASK_MARKERS = [
    "тебе нужно",
    "вам нужно",
    "нужно",
    "надо",
    "необходимо",
    "прошу",
    "сделай",
    "подготовь",
    "напиши",
    "продумай",
    "пришли",
    "отправь",
    "подготовьте",
    "please",
    "need",
    "must",
    "should",
    "prepare",
    "send",
    "write",
]


def get_current_datetime() -> str:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


def _build_context_prompt(text: str, context_messages: Optional[List[Dict[str, Any]]] = None) -> str:
    lines = ["CURRENT MESSAGE:", text.strip()]

    if context_messages:
        lines.extend(["", "RECENT CHAT CONTEXT (oldest to newest):"])
        for item in context_messages:
            body = (item.get("text") or "").strip()
            if not body:
                continue
            sender = item.get("sender") or "unknown"
            sent_at = item.get("date") or ""
            prefix = f"[{sent_at}] {sender}".strip()
            lines.append(f"{prefix}: {body}")

    return "\n".join(lines)


def _clean_email_title(subject: str, body_text: str) -> str:
    subject = (subject or "").strip().strip(" .;:-")
    body_text = (body_text or "").strip()

    if subject and len(subject) <= 120:
        return subject

    first_sentence = re.split(r"[.!?\n]+", body_text, maxsplit=1)[0].strip()
    first_sentence = re.sub(
        r"^(привет|добрый день|здравствуй|здравствуйте|hello|hi)\s+[^\s,]+,?\s*",
        "",
        first_sentence,
        flags=re.IGNORECASE,
    )
    first_sentence = re.sub(r"^(тебе|вам)\s+нужно\s+", "", first_sentence, flags=re.IGNORECASE)
    first_sentence = re.sub(r"^(нужно|надо|необходимо|прошу)\s+", "", first_sentence, flags=re.IGNORECASE)
    first_sentence = re.sub(r"\s+до\s+.*$", "", first_sentence, flags=re.IGNORECASE)
    first_sentence = re.sub(r"\s+", " ", first_sentence).strip(" ,.;:-")
    return first_sentence[:120] if first_sentence else "Задача из email"


def _extract_relative_due_date(text: str) -> Optional[datetime]:
    if not text:
        return None

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    text_lower = text.lower()

    if "сегодня" in text_lower:
        return now.replace(hour=18, minute=0, second=0, microsecond=0)

    if "завтра" in text_lower:
        target = now + timedelta(days=1)
        return target.replace(hour=18, minute=0, second=0, microsecond=0)

    days_match = re.search(r"через\s+(\d+)\s+(дн|дня|дней)", text_lower)
    if days_match:
        target = now + timedelta(days=int(days_match.group(1)))
        return target.replace(hour=18, minute=0, second=0, microsecond=0)

    for word, weekday in RUS_WEEKDAYS.items():
        if re.search(rf"(до|к)\s+(этой\s+|этому\s+)?{word}\b", text_lower):
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = now + timedelta(days=days_ahead)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

    return None


def _infer_email_priority(text: str) -> str:
    text_lower = (text or "").lower()
    if any(marker in text_lower for marker in ["срочно", "asap", "urgent", "critical"]):
        return "high"
    if "не срочно" in text_lower or "when you have time" in text_lower:
        return "low"
    return "normal"


def _extract_task_from_email_fallback(text: str) -> Optional[Dict[str, Any]]:
    if not text or not text.strip():
        return None

    subject_match = re.search(r"EMAIL SUBJECT:\s*(.+?)(?:\n|$)", text, flags=re.IGNORECASE | re.DOTALL)
    body_match = re.search(
        r"EMAIL BODY:\s*(.+?)(?:\n(?:Use quoted thread|ATTACHMENTS:)|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    subject = subject_match.group(1).strip() if subject_match else ""
    body_text = body_match.group(1).strip() if body_match else text.strip()
    body_lower = body_text.lower()

    if not any(marker in body_lower for marker in EMAIL_TASK_MARKERS):
        return None

    if any(noise in body_lower for noise in ["скидка", "newsletter", "unsubscribe", "чек", "receipt", "promo"]):
        return None

    due_date = _extract_relative_due_date(body_text)
    description = re.sub(r"\s+", " ", body_text).strip()
    title = _clean_email_title(subject, body_text)

    if not title or len(title) < 4:
        title = "Задача из email"

    return {
        "has_task": True,
        "task": {
            "title": title,
            "description": description or title,
            "assignee_usernames": [],
            "due_date": due_date.strftime("%Y-%m-%d %H:%M:%S") if due_date else None,
            "priority": _infer_email_priority(f"{subject}\n{body_text}"),
        },
    }


def _normalize_task_result(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not result or not isinstance(result, dict) or "has_task" not in result:
        logger.error(f"Invalid AI response format: {result}")
        return None

    if not result.get("has_task", False):
        return {"has_task": False, "task": None}

    task = result.get("task") or {}
    title = (task.get("title") or "").strip()
    description = (task.get("description") or "").strip()

    if not title and description:
        title = description[:100]
    if not description and title:
        description = title

    task["title"] = title
    task["description"] = description

    if not isinstance(task.get("assignee_usernames"), list):
        single_assignee = task.get("assignee_username")
        task["assignee_usernames"] = [single_assignee] if single_assignee else []

    if task.get("due_date"):
        try:
            task["due_date_parsed"] = date_parser.parse(task["due_date"])
        except Exception as date_error:
            logger.warning(f"Failed to parse due_date: {task.get('due_date')}, error: {date_error}")
            task["due_date_parsed"] = _extract_relative_due_date(f"{task.get('title', '')} {task.get('description', '')}")
    else:
        task["due_date_parsed"] = _extract_relative_due_date(f"{task.get('title', '')} {task.get('description', '')}")
        if task["due_date_parsed"]:
            task["due_date"] = task["due_date_parsed"].strftime("%Y-%m-%d %H:%M:%S")

    result["task"] = task
    return result


async def analyze_message_with_ai(
    text: str,
    context_messages: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    if not text or len(text.strip()) == 0:
        return None

    try:
        current_dt = get_current_datetime()
        system_prompt = CHAT_CONTEXT_SYSTEM_PROMPT.format(current_datetime=current_dt)
        user_prompt = _build_context_prompt(text, context_messages)

        logger.info(f"Calling configured AI provider to analyze message with context: {text[:50]}...")
        provider = get_ai_provider()
        result = await provider.analyze_message(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )
        logger.info(f"AI provider response: {result}")
        return _normalize_task_result(result)
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}", exc_info=True)
        return None


async def analyze_email_with_ai(text: str) -> Optional[Dict[str, Any]]:
    if not text or len(text.strip()) == 0:
        return None

    try:
        current_dt = get_current_datetime()
        system_prompt = EMAIL_SYSTEM_PROMPT.format(current_datetime=current_dt)

        logger.info(f"Calling configured AI provider to analyze email: {text[:50]}...")
        provider = get_ai_provider()
        result = await provider.analyze_email(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )
        logger.info(f"AI provider response for email: {result}")

        normalized = _normalize_task_result(result)
        if normalized and normalized.get("has_task"):
            return normalized

        fallback = _extract_task_from_email_fallback(text)
        if fallback:
            logger.info(f"Email fallback extractor found task: {fallback}")
            return _normalize_task_result(fallback)

        return normalized
    except Exception as e:
        logger.error(f"Error in AI email analysis: {e}", exc_info=True)
        fallback = _extract_task_from_email_fallback(text)
        if fallback:
            logger.info(f"Email fallback extractor found task after AI failure: {fallback}")
            return _normalize_task_result(fallback)
        return None


def extract_task_simple(text: str) -> bool:
    if not text:
        return False

    text_lower = text.lower()
    task_keywords = [
        "сделать", "нужно", "необходимо", "надо", "требуется", "выполни", "подготовь",
        "создай", "напиши", "исправь", "проверь", "убедись", "организуй", "настрой",
        "собери", "отправь", "согласуй", "подумай", "подготовьте", "прошу", "нужно бы",
        "срочно", "важно", "deadline", "need", "should", "must", "todo", "task",
        "please", "fix", "create", "update", "check", "send", "prepare"
    ]

    if any(keyword in text_lower for keyword in task_keywords):
        return True

    if '@' in text:
        return True

    return False


async def analyze_message(
    text: str,
    use_ai: bool = True,
    context_messages: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    if use_ai:
        try:
            result = await analyze_message_with_ai(text, context_messages=context_messages)
            if result is not None:
                return result
            logger.warning("AI returned None, using simple extraction")
        except Exception as e:
            logger.error(f"AI analysis failed: {e}, using simple extraction")

    has_task = extract_task_simple(text)
    if has_task:
        return {
            "has_task": True,
            "task": {
                "title": text[:100],
                "description": text,
                "assignee_username": None,
                "assignee_usernames": [],
                "due_date": None,
                "due_date_parsed": None,
                "priority": "normal"
            }
        }

    return {
        "has_task": False,
        "task": None
    }
