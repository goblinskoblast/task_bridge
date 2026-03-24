import json
import logging
from datetime import timedelta, timezone
from typing import Optional
from urllib import request as urlrequest

from sqlalchemy.orm import Session

from bot.email_handler import _get_google_access_token, GOOGLE_REFRESH_PREFIX, YANDEX_REFRESH_PREFIX
from config import TIMEZONE
from db.models import EmailAccount, Task, User

logger = logging.getLogger(__name__)


def _pick_calendar_account(user: User, db: Session) -> Optional[EmailAccount]:
    accounts = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.is_active == True
        )
        .order_by(EmailAccount.created_at.asc())
        .all()
    )

    if not accounts:
        return None

    for account in accounts:
        secret = account.imap_password or ""
        if secret.startswith(GOOGLE_REFRESH_PREFIX):
            return account

    for account in accounts:
        secret = account.imap_password or ""
        if secret.startswith(YANDEX_REFRESH_PREFIX):
            return account

    return None


def _build_task_event_payload(task: Task) -> Optional[dict]:
    due_date = task.due_date
    if not due_date:
        return None

    due_date_local = due_date
    if due_date_local.tzinfo is not None:
        due_date_local = due_date_local.astimezone(timezone.utc).replace(tzinfo=None)

    event_day = due_date_local.date()

    description_parts = []
    if task.description:
        description_parts.append(task.description)
    description_parts.append(f"TaskBridge task #{task.id}")
    description_parts.append(f"Priority: {task.priority}")
    description_parts.append(f"Status: {task.status}")

    return {
        "summary": task.title,
        "description": "\n\n".join(description_parts),
        "start": {
            "date": event_day.isoformat(),
            "timeZone": TIMEZONE,
        },
        "end": {
            "date": (event_day + timedelta(days=1)).isoformat(),
            "timeZone": TIMEZONE,
        },
    }


def _sync_google_calendar(task: Task, account: EmailAccount) -> bool:
    refresh_token = (account.imap_password or "")[len(GOOGLE_REFRESH_PREFIX):]
    access_token = _get_google_access_token(refresh_token)
    if not access_token:
        logger.error("Failed to get Google Calendar access token for %s", account.email_address)
        return False

    event_payload = _build_task_event_payload(task)
    if not event_payload:
        logger.info("Skip calendar sync for task %s: due_date is not set", task.id)
        return False

    payload = json.dumps(event_payload).encode("utf-8")
    req = urlrequest.Request(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events?sendUpdates=none",
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        logger.info(
            "Google Calendar event created for task %s: %s",
            task.id,
            response_payload.get("htmlLink", "no-link"),
        )
        return True
    except Exception as e:
        logger.error("Failed to create Google Calendar event for task %s: %s", task.id, e)
        return False


def sync_task_to_user_calendar(task: Task, user: User, db: Session) -> bool:
    account = _pick_calendar_account(user, db)
    if not account:
        logger.info("No calendar-capable email account found for user %s", user.id)
        return False

    secret = account.imap_password or ""
    if secret.startswith(GOOGLE_REFRESH_PREFIX):
        return _sync_google_calendar(task, account)

    if secret.startswith(YANDEX_REFRESH_PREFIX):
        logger.warning(
            "Yandex calendar auto-sync skipped for user %s. Current Yandex integration uses mail OAuth, "
            "while Yandex officially documents calendar sync through CalDAV/app password.",
            user.id,
        )
        return False

    logger.info("Email account %s is not calendar-synced", account.email_address)
    return False


def sync_task_to_connected_calendars(task: Task, db: Session) -> int:
    synced_count = 0
    target_users = list(task.assignees) if task.assignees else []

    if not target_users and task.creator:
        target_users = [task.creator]

    for user in target_users:
        try:
            if sync_task_to_user_calendar(task, user, db):
                synced_count += 1
        except Exception as e:
            logger.error("Calendar sync failed for task %s and user %s: %s", task.id, user.id, e)

    return synced_count
