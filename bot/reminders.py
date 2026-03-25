import logging
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from sqlalchemy.orm import Session

from config import (
    REMINDER_INTERVALS, ASSIGNEE_REMINDER_INTERVALS, CREATOR_REMINDER_INTERVALS,
    REMINDER_TIME_HOUR, REMINDER_CHECK_INTERVAL, TIMEZONE
)
from db.models import Task, User
from db.database import get_db_session

logger = logging.getLogger(__name__)


scheduler = None
DEFAULT_PRIORITY_REMINDER_HOURS = {
    "low": 6,
    "normal": 3,
    "high": 2,
    "urgent": 2,
}


def get_default_reminder_interval_hours(priority: str) -> int:
    return DEFAULT_PRIORITY_REMINDER_HOURS.get((priority or "normal").lower(), 3)


def get_effective_reminder_interval_hours(task: Task) -> int:
    if task.reminder_interval_hours and task.reminder_interval_hours > 0:
        return task.reminder_interval_hours
    return get_default_reminder_interval_hours(task.priority)


def _was_creator_reminder_sent_for_interval(task: Task, interval_days: int) -> bool:
    if not task.last_creator_reminder_sent_at or not task.created_at:
        return False

    last_days_since_created = (
        task.last_creator_reminder_sent_at - task.created_at
    ).total_seconds() / (24 * 3600)
    return abs(last_days_since_created - interval_days) < 0.5


async def send_assignee_reminder(bot: Bot, task: Task, assignee: User, reminder_type: str = "upcoming"):
    try:
        if not assignee or assignee.telegram_id == -1:
            logger.warning(f"Assignee for task {task.id} hasn't started bot")
            return False

        if reminder_type == "due_today":
            emoji = "⏰"
            title = "Дедлайн сегодня"
        elif reminder_type == "overdue":
            emoji = "⚠️"
            title = "Задача просрочена"
        elif reminder_type == "scheduled":
            emoji = "🔔"
            title = "Плановое напоминание"
        else:
            emoji = "📌"
            title = "Напоминание по задаче"

        notification = (
            f"{emoji} <b>{title}</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
        )

        if task.description and task.description != task.title:
            notification += f"<b>Описание:</b> {task.description}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"<b>Приоритет:</b> {task.priority}\n"
        notification += f"<b>Статус:</b> {task.status}\n"
        notification += f"<b>Интервал напоминаний:</b> каждые {get_effective_reminder_interval_hours(task)} ч\n"

        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=notification,
            parse_mode="HTML"
        )

        logger.info(f"Assignee reminder sent for task {task.id} to user {assignee.telegram_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send assignee reminder for task {task.id}: {e}")
        return False


async def send_creator_reminder(bot: Bot, task: Task):
    try:
        if not task.creator or task.creator.telegram_id == -1:
            logger.warning(f"Creator of task {task.id} hasn't started bot")
            return False

        status_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "cancelled": "❌"
        }

        status_text = {
            "pending": "В ожидании",
            "in_progress": "В работе",
            "completed": "Завершена",
            "cancelled": "Отменена"
        }

        emoji = status_emoji.get(task.status, "📋")
        status = status_text.get(task.status, task.status)
        days_since_created = (datetime.utcnow() - task.created_at).days

        notification = (
            f"{emoji} <b>Обновление статуса задачи</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Статус:</b> {status}\n"
            f"<b>Приоритет:</b> {task.priority}\n"
        )

        if task.assignees:
            assignees_names = ", ".join(
                [a.first_name or a.username for a in task.assignees if a.first_name or a.username]
            )
            notification += f"<b>Исполнители:</b> {assignees_names}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"\n📅 Создана {days_since_created} дн. назад"

        if task.status in ["pending", "in_progress"] and task.due_date:
            days_until_due = (task.due_date - datetime.utcnow()).days
            if days_until_due < 0:
                notification += f"\n⚠️ Просрочено на {abs(days_until_due)} дн."
            else:
                notification += f"\n⏰ Осталось {days_until_due} дн."

        await bot.send_message(
            chat_id=task.creator.telegram_id,
            text=notification,
            parse_mode="HTML"
        )

        logger.info(f"Creator reminder sent for task {task.id} to creator {task.creator.telegram_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send creator reminder for task {task.id}: {e}")
        return False


async def send_reminder(bot: Bot, task: Task, db: Session, reminder_type: str = "upcoming"):
    if getattr(task, "assignee", None):
        await send_assignee_reminder(bot, task, task.assignee, reminder_type)


async def check_and_send_reminders(bot: Bot):
    db = get_db_session()

    try:
        logger.info("Checking tasks for reminders...")

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        active_tasks = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"])
        ).all()

        logger.info(f"Found {len(active_tasks)} active tasks")

        for task in active_tasks:
            try:
                if task.assignees:
                    interval_hours = get_effective_reminder_interval_hours(task)
                    if task.last_assignee_reminder_sent_at:
                        hours_since_last = (
                            datetime.utcnow() - task.last_assignee_reminder_sent_at
                        ).total_seconds() / 3600
                        if hours_since_last < interval_hours:
                            continue

                    reminder_type = "scheduled"
                    if task.due_date:
                        task_due_date = tz.localize(task.due_date) if task.due_date.tzinfo is None else task.due_date
                        hours_until_due = (task_due_date - now).total_seconds() / 3600
                        if hours_until_due < 0:
                            reminder_type = "overdue"
                        elif hours_until_due <= 24:
                            reminder_type = "due_today"
                        else:
                            reminder_type = "upcoming"

                    sent = False
                    for assignee in task.assignees:
                        if await send_assignee_reminder(bot, task, assignee, reminder_type):
                            sent = True

                    if sent:
                        task.last_assignee_reminder_sent_at = datetime.utcnow()

                if not task.creator:
                    continue

                task_created_at = tz.localize(task.created_at) if task.created_at.tzinfo is None else task.created_at
                time_since_created = now - task_created_at
                days_since_created = time_since_created.total_seconds() / (24 * 3600)

                for interval in CREATOR_REMINDER_INTERVALS:
                    if abs(days_since_created - interval) < 0.5 and not _was_creator_reminder_sent_for_interval(task, interval):
                        logger.info(f"Task {task.id} was created {interval} days ago, sending creator reminder")
                        if await send_creator_reminder(bot, task):
                            task.last_creator_reminder_sent_at = datetime.utcnow()
                        break

            except Exception as task_error:
                logger.error(f"Error processing task {task.id} for reminders: {task_error}", exc_info=True)
                continue

        db.commit()
    except Exception as e:
        logger.error(f"Error in check_and_send_reminders: {e}", exc_info=True)
    finally:
        db.close()


def start_reminder_scheduler(bot: Bot):
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler is already running")
        return

    try:
        scheduler = AsyncIOScheduler(timezone=TIMEZONE)

        scheduler.add_job(
            check_and_send_reminders,
            "interval",
            minutes=REMINDER_CHECK_INTERVAL,
            args=[bot],
            id="check_reminders",
            replace_existing=True
        )

        from bot.email_processor import check_and_process_emails
        scheduler.add_job(
            check_and_process_emails,
            "interval",
            minutes=10,
            next_run_time=datetime.now(pytz.timezone(TIMEZONE)) + timedelta(minutes=1),
            id="check_emails",
            replace_existing=True
        )

        scheduler.start()

        logger.info(f"Reminder scheduler started with interval {REMINDER_CHECK_INTERVAL} minutes")
        logger.info("Email checker started: first run in 1 minute, then every 10 minutes")
    except Exception as e:
        logger.error(f"Failed to start reminder scheduler: {e}", exc_info=True)


def stop_reminder_scheduler():
    global scheduler

    if scheduler is not None:
        try:
            scheduler.shutdown()
            scheduler = None
            logger.info("Reminder scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
