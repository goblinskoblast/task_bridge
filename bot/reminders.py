import logging
from datetime import datetime, timedelta
from typing import List
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


async def send_assignee_reminder(bot: Bot, task: Task, assignee: User, reminder_type: str = "upcoming"):
    """Отправляет напоминание исполнителю о задаче"""
    try:
        if not assignee or assignee.telegram_id == -1:
            logger.warning(f"Assignee for task {task.id} hasn't started bot")
            return

        if reminder_type == "upcoming":
            days_left = (task.due_date - datetime.now()).days
            emoji = "📅"
            title = f"Напоминание: До дедлайна {days_left} дн."
        elif reminder_type == "due_today":
            emoji = "⏰"
            title = "Внимание: Дедлайн сегодня!"
        else:
            emoji = "⚠️"
            title = "ПРОСРОЧЕНО"

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

        await bot.send_message(
            chat_id=assignee.telegram_id,
            text=notification,
            parse_mode="HTML"
        )

        logger.info(f"Assignee reminder sent for task {task.id} to user {assignee.telegram_id}")

    except Exception as e:
        logger.error(f"Failed to send assignee reminder for task {task.id}: {e}")


async def send_creator_reminder(bot: Bot, task: Task):
    """Отправляет напоминание создателю задачи о статусе"""
    try:
        if not task.creator or task.creator.telegram_id == -1:
            logger.warning(f"Creator of task {task.id} hasn't started bot")
            return

        # Определяем emoji и текст в зависимости от статуса
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

        # Вычисляем время с момента создания
        days_since_created = (datetime.now() - task.created_at).days

        notification = (
            f"{emoji} <b>Обновление статуса задачи</b>\n\n"
            f"<b>Задача:</b> {task.title}\n"
            f"<b>Статус:</b> {status}\n"
            f"<b>Приоритет:</b> {task.priority}\n"
        )

        # Добавляем информацию об исполнителях
        if task.assignees:
            assignees_names = ", ".join([a.first_name or a.username for a in task.assignees if a.first_name or a.username])
            notification += f"<b>Исполнители:</b> {assignees_names}\n"

        if task.due_date:
            notification += f"<b>Срок:</b> {task.due_date.strftime('%d.%m.%Y %H:%M')}\n"

        notification += f"\n📅 Создана {days_since_created} дн. назад"

        if task.status in ["pending", "in_progress"] and task.due_date:
            days_until_due = (task.due_date - datetime.now()).days
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

    except Exception as e:
        logger.error(f"Failed to send creator reminder for task {task.id}: {e}")


# Legacy function for backward compatibility
async def send_reminder(bot: Bot, task: Task, db: Session, reminder_type: str = "upcoming"):
    """Legacy function - sends reminder to assignee (backward compatibility)"""
    if task.assignee:
        await send_assignee_reminder(bot, task, task.assignee, reminder_type)


async def check_and_send_reminders(bot: Bot):
    """
    Проверяет все задачи и отправляет напоминания по мере необходимости
    """
    db = get_db_session()

    try:
        logger.info("Checking tasks for reminders...")

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        # ЧАСТЬ 1: Напоминания исполнителям о дедлайнах
        tasks_with_deadlines = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"]),
            Task.due_date.isnot(None)
        ).all()

        logger.info(f"Found {len(tasks_with_deadlines)} active tasks with deadlines")

        for task in tasks_with_deadlines:
            try:
                # Проверяем что есть исполнители
                if not task.assignees:
                    continue

                if task.due_date.tzinfo is None:
                    task_due_date = tz.localize(task.due_date)
                else:
                    task_due_date = task.due_date

                time_diff = task_due_date - now
                days_until_due = time_diff.days
                hours_until_due = time_diff.total_seconds() / 3600

                reminder_type = None

                if hours_until_due < 0:
                    days_overdue = abs(days_until_due)
                    logger.info(f"Task {task.id} is overdue by {days_overdue} days")
                    reminder_type = "overdue"
                elif 0 <= hours_until_due <= 24:
                    logger.info(f"Task {task.id} is due today ({hours_until_due:.1f} hours left)")
                    reminder_type = "due_today"
                else:
                    # Проверяем интервалы напоминаний
                    for interval in ASSIGNEE_REMINDER_INTERVALS:
                        if interval > 0:
                            days_diff = time_diff.total_seconds() / (24 * 3600)
                            if abs(days_diff - interval) < 0.5:
                                logger.info(f"Task {task.id} is due in ~{interval} days")
                                reminder_type = "upcoming"
                                break

                # Отправляем напоминание ВСЕМ исполнителям
                if reminder_type:
                    for assignee in task.assignees:
                        await send_assignee_reminder(bot, task, assignee, reminder_type)

            except Exception as task_error:
                logger.error(f"Error processing task {task.id} for assignee reminders: {task_error}", exc_info=True)
                continue

        # ЧАСТЬ 2: Напоминания постановщикам о статусе задач
        all_active_tasks = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"]),
            Task.created_by.isnot(None)
        ).all()

        logger.info(f"Found {len(all_active_tasks)} active tasks for creator reminders")

        for task in all_active_tasks:
            try:
                if not task.creator:
                    continue

                # Вычисляем дни с момента создания
                if task.created_at.tzinfo is None:
                    task_created_at = tz.localize(task.created_at)
                else:
                    task_created_at = task.created_at

                time_since_created = now - task_created_at
                days_since_created = time_since_created.total_seconds() / (24 * 3600)

                # Проверяем интервалы напоминаний для создателя
                for interval in CREATOR_REMINDER_INTERVALS:
                    if abs(days_since_created - interval) < 0.5:
                        logger.info(f"Task {task.id} was created {interval} days ago, sending creator reminder")
                        await send_creator_reminder(bot, task)
                        break

            except Exception as task_error:
                logger.error(f"Error processing task {task.id} for creator reminders: {task_error}", exc_info=True)
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

        # Задача для проверки напоминаний
        scheduler.add_job(
            check_and_send_reminders,
            'interval',
            minutes=REMINDER_CHECK_INTERVAL,
            args=[bot],
            id='check_reminders',
            replace_existing=True
        )

        # Задача для проверки email каждые 10 минут
        from bot.email_processor import check_and_process_emails
        scheduler.add_job(
            check_and_process_emails,
            'interval',
            minutes=10,  # Проверяем email каждые 10 минут
            id='check_emails',
            replace_existing=True
        )


        scheduler.start()

        logger.info(f"Reminder scheduler started with interval {REMINDER_CHECK_INTERVAL} minutes")
        logger.info("Email checker started with interval 10 minutes")

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
