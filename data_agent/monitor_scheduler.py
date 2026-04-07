from __future__ import annotations

import logging
import json
import hashlib
from datetime import datetime

import pytz
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, TIMEZONE
from db.database import get_db_session
from db.models import DataAgentMonitorConfig, DataAgentMonitorEvent, DataAgentProfile, DataAgentSystem, User

from .blanks_tool import blanks_tool
from .debugging import build_debug_artifacts
from .review_report import review_report_service
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)

_scheduler = None


def _resolve_monitor_delivery_chat_id(db, user: User | None) -> int | None:
    if not user:
        return None

    profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
    if profile and profile.default_report_chat_id:
        return int(profile.default_report_chat_id)

    if user.telegram_id and user.telegram_id != -1:
        return int(user.telegram_id)

    return None


def _build_monitor_failure_hash(config: DataAgentMonitorConfig, result: dict) -> str:
    payload = {
        "monitor_type": config.monitor_type,
        "point_name": config.point_name,
        "result": result,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _build_monitor_failure_message(config: DataAgentMonitorConfig, summary: str) -> str:
    return (
        "Мониторинг завершился с ошибкой\n\n"
        f"Тип: {config.monitor_type}\n"
        f"Точка: {config.point_name}\n\n"
        f"{summary}"
    )[:3500]


async def _record_monitor_failure(bot: Bot, db, config: DataAgentMonitorConfig, result: dict, tool_name: str) -> None:
    config.last_checked_at = datetime.utcnow()
    config.last_status = result.get("status") or "failed"
    config.last_result_json = result

    failure_hash = result.get("alert_hash") or _build_monitor_failure_hash(config, result)
    if failure_hash == config.last_alert_hash:
        db.commit()
        return

    payload, summary = build_debug_artifacts(
        trace_id=f"monitor-{config.id}",
        scenario=f"{config.monitor_type}_monitor",
        status="failed",
        selected_tools=[tool_name],
        tool_results={tool_name: result},
    )

    event = DataAgentMonitorEvent(
        user_id=config.user_id,
        config_id=config.id,
        system_name=config.system_name,
        monitor_type=config.monitor_type,
        point_name=config.point_name,
        severity="error",
        title=f"Мониторинг завершился с ошибкой: {config.point_name}",
        body=summary,
        event_hash=failure_hash,
        sent_to_telegram=False,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    user = db.query(User).filter(User.id == config.user_id).first()
    delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user)
    if delivery_chat_id:
        await bot.send_message(
            chat_id=delivery_chat_id,
            text=_build_monitor_failure_message(config, summary),
        )
        event.sent_to_telegram = True

    config.last_alert_hash = failure_hash
    config.last_result_json = payload
    db.commit()


async def _run_blanks_monitor(bot: Bot, config: DataAgentMonitorConfig) -> None:
    db = get_db_session()
    try:
        system = (
            db.query(DataAgentSystem)
            .filter(
                DataAgentSystem.user_id == config.user_id,
                DataAgentSystem.is_active == True,
                DataAgentSystem.url.contains("tochka.italianpizza.ru"),
            )
            .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
            .first()
        )
        if not system:
            await _record_monitor_failure(
                bot,
                db,
                config,
                {
                    "status": "system_not_connected",
                    "message": "Italian Pizza портал не подключён для мониторинга бланков.",
                },
                "blanks_tool",
            )
            return

        result = await blanks_tool.inspect_point(
            url=system.url,
            username=system.login,
            encrypted_password=system.encrypted_password,
            point_name=config.point_name,
        )

        result_status = result.get("status") or "ok"
        if result_status in {"failed", "error", "system_not_connected"}:
            await _record_monitor_failure(bot, db, config, result, "blanks_tool")
            return

        config.last_checked_at = datetime.utcnow()
        config.last_status = result_status
        config.last_result_json = result

        if result.get("has_red_flags") and result.get("alert_hash") != config.last_alert_hash:
            event = DataAgentMonitorEvent(
                user_id=config.user_id,
                config_id=config.id,
                system_name=config.system_name,
                monitor_type=config.monitor_type,
                point_name=config.point_name,
                severity="warning",
                title=f"Найдены красные бланки: {config.point_name}",
                body=result.get("report_text"),
                event_hash=result.get("alert_hash"),
                sent_to_telegram=False,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            user = db.query(User).filter(User.id == config.user_id).first()
            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user)
            if delivery_chat_id:
                await bot.send_message(
                    chat_id=delivery_chat_id,
                    text=(
                        f"Обнаружены красные бланки\n\n"
                        f"<b>Точка:</b> {config.point_name}\n"
                        f"<b>Статус:</b> найдены красные бланки\n\n"
                        f"{result.get('report_text', '')[:3500]}"
                    ),
                    parse_mode="HTML",
                )
                event.sent_to_telegram = True
                config.last_alert_hash = result.get("alert_hash")
                db.commit()
        else:
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Blanks monitor failed for config %s: %s", config.id, exc, exc_info=True)
    finally:
        db.close()


async def _run_stoplist_monitor(bot: Bot, config: DataAgentMonitorConfig) -> None:
    db = get_db_session()
    try:
        result = await stoplist_tool.collect_for_point(
            url="",
            username="",
            encrypted_password="",
            point_name=config.point_name,
        )

        result_status = result.get("status") or "ok"
        if result_status in {"failed", "error", "system_not_connected"}:
            await _record_monitor_failure(bot, db, config, result, "stoplist_tool")
            return

        config.last_checked_at = datetime.utcnow()
        config.last_status = result_status
        config.last_result_json = result

        report_text = str(result.get("report_text") or "").strip()
        report_hash = result.get("alert_hash") or None
        if report_text and report_hash is None:
            report_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()

        if report_hash and report_hash != config.last_alert_hash:
            event = DataAgentMonitorEvent(
                user_id=config.user_id,
                config_id=config.id,
                system_name=config.system_name,
                monitor_type=config.monitor_type,
                point_name=config.point_name,
                severity="info",
                title=f"Обновился стоп-лист: {config.point_name}",
                body=report_text,
                event_hash=report_hash,
                sent_to_telegram=False,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            user = db.query(User).filter(User.id == config.user_id).first()
            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user)
            if delivery_chat_id:
                await bot.send_message(
                    chat_id=delivery_chat_id,
                    text=(
                        f"Стоп-лист изменился\n\n"
                        f"<b>Точка:</b> {config.point_name}\n\n"
                        f"{report_text[:3500]}"
                    ),
                    parse_mode="HTML",
                )
                event.sent_to_telegram = True
                config.last_alert_hash = report_hash
                db.commit()
        else:
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Stoplist monitor failed for config %s: %s", config.id, exc, exc_info=True)
    finally:
        db.close()


async def _run_reviews_monitor(bot: Bot, config: DataAgentMonitorConfig) -> None:
    db = get_db_session()
    try:
        interval = config.check_interval_minutes or 60
        if interval <= 180:
            window_label = "за последние 3 часов"
        elif interval <= 1440:
            window_label = "за последние 24 часов"
        else:
            window_label = "за последние 7 дней"

        result = await review_report_service.build_report_for_window_label(window_label)

        result_status = result.get("status") or "ok"
        if result_status in {"failed", "error", "system_not_connected"}:
            await _record_monitor_failure(bot, db, config, result, "review_tool")
            return

        config.last_checked_at = datetime.utcnow()
        config.last_status = result_status
        config.last_result_json = result

        report_text = str(result.get("report_text") or "").strip()
        report_hash = result.get("alert_hash") or None
        if report_text and report_hash is None:
            report_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()

        if report_hash and report_hash != config.last_alert_hash:
            event = DataAgentMonitorEvent(
                user_id=config.user_id,
                config_id=config.id,
                system_name=config.system_name,
                monitor_type=config.monitor_type,
                point_name=config.point_name,
                severity="info",
                title="Обновился отчёт по отзывам",
                body=report_text,
                event_hash=report_hash,
                sent_to_telegram=False,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            user = db.query(User).filter(User.id == config.user_id).first()
            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user)
            if delivery_chat_id:
                await bot.send_message(
                    chat_id=delivery_chat_id,
                    text=(
                        "Обновился отчёт по отзывам\n\n"
                        f"{report_text[:3500]}"
                    ),
                    parse_mode="HTML",
                )
                event.sent_to_telegram = True
                config.last_alert_hash = report_hash
                db.commit()
        else:
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Reviews monitor failed for config %s: %s", config.id, exc, exc_info=True)
    finally:
        db.close()


async def _run_monitors(bot: Bot) -> None:
    db = get_db_session()
    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        configs = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.is_active == True).all()
        logger.info("Running data-agent monitors: %s active configs", len(configs))

        for item in configs:
            if item.last_checked_at:
                elapsed_minutes = (now.replace(tzinfo=None) - item.last_checked_at).total_seconds() / 60
                if elapsed_minutes < item.check_interval_minutes:
                    continue

            if item.monitor_type == "blanks":
                await _run_blanks_monitor(bot, item)
            elif item.monitor_type == "stoplist":
                await _run_stoplist_monitor(bot, item)
            elif item.monitor_type == "reviews":
                await _run_reviews_monitor(bot, item)
    finally:
        db.close()


def start_data_agent_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    bot = Bot(token=BOT_TOKEN)
    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _scheduler.add_job(_run_monitors, "interval", minutes=60, args=[bot], id="data_agent_monitors", replace_existing=True)
    _scheduler.start()
    logger.info("Data-agent monitor scheduler started with interval 60 minutes")


def stop_data_agent_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
