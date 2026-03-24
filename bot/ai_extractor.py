import logging
from datetime import datetime
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
- Treat polite business wording as a task when there is an expected result: "please prepare", "could you send", "I need by Friday", "waiting for", "вам нужно", "прошу направить", "ожидаю".
- If the body contains a question that already encodes a deadline or expectation, treat it as a task, not as a casual question.
- Ignore ads, promo, receipts, newsletters, and service notifications unless they contain a concrete task.
- Return one primary task only.
- Build a short clean title and a fuller description.
- assignee_usernames should normally be an empty array for email flow.
- Convert relative deadlines into absolute format YYYY-MM-DD HH:MM:SS when possible, otherwise null.
- Priority mapping: urgent/high for срочно, asap, urgent, critical; low for when you have time, не срочно; otherwise normal.

Return ONLY JSON in the same schema as chat extraction.
""".strip()


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
            task["due_date_parsed"] = None
    else:
        task["due_date_parsed"] = None

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
        return _normalize_task_result(result)
    except Exception as e:
        logger.error(f"Error in AI email analysis: {e}", exc_info=True)
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
