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
from .point_statistics import point_statistics_service
from .review_report import review_report_service
from .stoplist_tool import stoplist_tool

logger = logging.getLogger(__name__)

_scheduler = None


def _result_alert_hash(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    explicit_hash = str(result.get("alert_hash") or "").strip()
    if explicit_hash:
        return explicit_hash
    report_text = str(result.get("report_text") or "").strip()
    if not report_text:
        return None
    return hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()


def _result_has_red_flags(result: dict | None) -> bool:
    return bool(isinstance(result, dict) and result.get("has_red_flags"))


def _load_monitor_config(db, config: DataAgentMonitorConfig | None) -> DataAgentMonitorConfig | None:
    config_id = getattr(config, "id", None)
    if not config_id:
        return None
    return db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.id == config_id).first()


def _resolve_monitor_delivery_chat_id(db, user: User | None, category: str | None = None) -> int | None:
    if not user:
        return None

    profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user.id).first()
    if profile and category:
        category_field = {
            "reviews": "reviews_report_chat_id",
            "stoplist": "stoplist_report_chat_id",
            "blanks": "blanks_report_chat_id",
        }.get(category)
        if category_field:
            category_chat_id = getattr(profile, category_field, None)
            if category_chat_id:
                return int(category_chat_id)

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
    templates = {
        "stoplist": "Не удалось получить отчет по стоп-листу. Попробуйте позже.",
        "blanks": "Не удалось получить отчет по бланкам. Попробуйте позже.",
        "reviews": "Не удалось получить отчет по отзывам. Попробуйте позже.",
    }
    return templates.get(config.monitor_type, "Не удалось получить отчет. Попробуйте позже.")


def _is_within_active_window(config: DataAgentMonitorConfig, now: datetime) -> bool:
    start_hour = config.active_from_hour
    end_hour = config.active_to_hour
    if start_hour is None or end_hour is None:
        return True

    current_hour = now.hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= current_hour <= end_hour
    return current_hour >= start_hour or current_hour <= end_hour


def _hours_word(hours: int) -> str:
    remainder_10 = hours % 10
    remainder_100 = hours % 100
    if remainder_10 == 1 and remainder_100 != 11:
        return "час"
    if remainder_10 in {2, 3, 4} and remainder_100 not in {12, 13, 14}:
        return "часа"
    return "часов"


def _monitor_blanks_period_hint(config: DataAgentMonitorConfig) -> str:
    minutes = int(config.check_interval_minutes or 0)
    if minutes < 60:
        return "текущий бланк"
    hours = max(1, round(minutes / 60))
    return f"за последние {hours} {_hours_word(hours)}"


def _is_monitor_due(config: DataAgentMonitorConfig, now: datetime) -> bool:
    interval_minutes = int(config.check_interval_minutes or 0)
    if interval_minutes <= 0:
        return True

    if interval_minutes % 60 == 0:
        interval_hours = max(1, interval_minutes // 60)
        anchor_hour = config.active_from_hour if config.active_from_hour is not None else 0
        if now.minute != 0:
            return False
        if (now.hour - anchor_hour) % interval_hours != 0:
            return False
        if not config.last_checked_at:
            return True

        last_checked = config.last_checked_at
        if last_checked.tzinfo is None:
            last_checked = pytz.UTC.localize(last_checked).astimezone(now.tzinfo)
        else:
            last_checked = last_checked.astimezone(now.tzinfo)
        return not (last_checked.date() == now.date() and last_checked.hour == now.hour)

    if not config.last_checked_at:
        return True

    last_checked = config.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = pytz.UTC.localize(last_checked).astimezone(now.tzinfo)
    else:
        last_checked = last_checked.astimezone(now.tzinfo)
    elapsed_minutes = (now - last_checked).total_seconds() / 60
    return elapsed_minutes >= interval_minutes


async def _record_monitor_failure(
    bot: Bot,
    db,
    config: DataAgentMonitorConfig,
    result: dict,
    tool_name: str,
    *,
    notify_user: bool = True,
    persist_state: bool = True,
) -> dict:
    config = _load_monitor_config(db, config)
    if not config:
        return result

    if not persist_state and not notify_user:
        return result

    if persist_state:
        config.last_checked_at = datetime.utcnow()
        config.last_status = result.get("status") or "failed"
        config.last_result_json = result

    failure_hash = result.get("alert_hash") or _build_monitor_failure_hash(config, result)
    if persist_state and failure_hash == config.last_alert_hash:
        db.commit()
        return result

    payload, summary = build_debug_artifacts(
        trace_id=f"monitor-{config.id}",
        scenario=f"{config.monitor_type}_monitor",
        status="failed",
        selected_tools=[tool_name],
        tool_results={tool_name: result},
    )

    event = None
    if persist_state:
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

    if notify_user:
        user = db.query(User).filter(User.id == config.user_id).first()
        delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user, config.monitor_type)
        if delivery_chat_id:
            await bot.send_message(
                chat_id=delivery_chat_id,
                text=_build_monitor_failure_message(config, summary),
            )
            if event:
                event.sent_to_telegram = True

    if persist_state:
        config.last_alert_hash = failure_hash
        config.last_result_json = payload
        db.commit()
    return result


async def _run_blanks_monitor(
    bot: Bot,
    config: DataAgentMonitorConfig,
    *,
    notify_user: bool = True,
    persist_state: bool = True,
) -> dict | None:
    db = get_db_session()
    try:
        config = _load_monitor_config(db, config)
        if not config:
            return None

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
            return await _record_monitor_failure(
                bot,
                db,
                config,
                {
                    "status": "system_not_connected",
                    "message": "Italian Pizza портал не подключён для мониторинга бланков.",
                },
                "blanks_tool",
                notify_user=notify_user,
                persist_state=persist_state,
            )

        result = await blanks_tool.inspect_point(
            url=system.url,
            username=system.login,
            encrypted_password=system.encrypted_password,
            point_name=config.point_name,
            period_hint=_monitor_blanks_period_hint(config),
        )

        result_status = result.get("status") or "ok"
        if result_status in {"failed", "error", "system_not_connected"}:
            return await _record_monitor_failure(
                bot,
                db,
                config,
                result,
                "blanks_tool",
                notify_user=notify_user,
                persist_state=persist_state,
            )

        if not persist_state:
            return result

        previous_result = config.last_result_json if isinstance(config.last_result_json, dict) else {}
        previous_had_red_flags = _result_has_red_flags(previous_result)
        alert_hash = _result_alert_hash(result)
        has_red_flags = _result_has_red_flags(result)

        config.last_checked_at = datetime.utcnow()
        config.last_status = result_status
        config.last_result_json = result

        should_send_alert = has_red_flags and (
            not previous_had_red_flags or bool(alert_hash and alert_hash != config.last_alert_hash)
        )
        if should_send_alert:
            report_text = (result.get("report_text") or "").strip()
            red_summary = report_text
            event = DataAgentMonitorEvent(
                user_id=config.user_id,
                config_id=config.id,
                system_name=config.system_name,
                monitor_type=config.monitor_type,
                point_name=config.point_name,
                severity="critical",
                title=f"Найдены красные бланки: {config.point_name}",
                body=red_summary,
                event_hash=alert_hash,
                sent_to_telegram=False,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            user = db.query(User).filter(User.id == config.user_id).first()
            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user, "blanks")
            if notify_user and delivery_chat_id:
                await bot.send_message(
                    chat_id=delivery_chat_id,
                    text=(
                        f"Обнаружены красные бланки\n\n"
                        f"<b>Точка:</b> {config.point_name}\n"
                        f"<b>Статус:</b> найдены красные бланки\n\n"
                        f"{red_summary[:3500]}"
                    ),
                    parse_mode="HTML",
                )
                logger.info(
                    "Blanks monitor alert sent user_id=%s point=%s chat_id=%s alert_hash=%s",
                    config.user_id,
                    config.point_name,
                    delivery_chat_id,
                    alert_hash,
                )
                event.sent_to_telegram = True
            config.last_alert_hash = alert_hash
            db.commit()
        elif not has_red_flags:
            config.last_alert_hash = None
            db.commit()
        else:
            db.commit()
        return result
    except Exception as exc:
        db.rollback()
        logger.error("Blanks monitor failed for config %s: %s", config.id, exc, exc_info=True)
        return None
    finally:
        db.close()


async def _run_stoplist_monitor(
    bot: Bot,
    config: DataAgentMonitorConfig,
    *,
    notify_user: bool = True,
    persist_state: bool = True,
) -> dict | None:
    db = get_db_session()
    try:
        config = _load_monitor_config(db, config)
        if not config:
            return None

        user = db.query(User).filter(User.id == config.user_id).first()
        result = await stoplist_tool.collect_for_point(
            url="",
            username="",
            encrypted_password="",
            point_name=config.point_name,
        )
        if user and user.telegram_id:
            result = point_statistics_service.enrich_stoplist_report(user.telegram_id, config.point_name, result)

        result_status = result.get("status") or "ok"
        if result_status in {"failed", "error", "system_not_connected"}:
            return await _record_monitor_failure(
                bot,
                db,
                config,
                result,
                "stoplist_tool",
                notify_user=notify_user,
                persist_state=persist_state,
            )

        if not persist_state:
            return result

        config.last_checked_at = datetime.utcnow()
        config.last_status = result_status
        config.last_result_json = result

        report_text = str(result.get("report_text") or "").strip()
        report_hash = result.get("alert_hash") or None
        if report_text and report_hash is None:
            report_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()
        previous_hash = config.last_alert_hash
        changed = bool(report_hash and report_hash != previous_hash)

        if report_text:
            event = DataAgentMonitorEvent(
                user_id=config.user_id,
                config_id=config.id,
                system_name=config.system_name,
                monitor_type=config.monitor_type,
                point_name=config.point_name,
                severity="info",
                title=(f"Обновился стоп-лист: {config.point_name}" if changed else f"Стоп-лист по расписанию: {config.point_name}"),
                body=report_text,
                event_hash=hashlib.sha256(
                    f"{report_hash or 'stoplist'}:{datetime.utcnow().isoformat()}".encode("utf-8", errors="ignore")
                ).hexdigest(),
                sent_to_telegram=False,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user, "stoplist")
            if notify_user and delivery_chat_id:
                await bot.send_message(
                    chat_id=delivery_chat_id,
                    text=(
                        f"{'Стоп-лист изменился' if changed else 'Стоп-лист по расписанию'}\n\n"
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
        return result
    except Exception as exc:
        db.rollback()
        logger.error("Stoplist monitor failed for config %s: %s", config.id, exc, exc_info=True)
        return None
    finally:
        db.close()


async def _run_reviews_monitor(
    bot: Bot,
    config: DataAgentMonitorConfig,
    *,
    notify_user: bool = True,
    persist_state: bool = True,
) -> dict | None:
    db = get_db_session()
    try:
        config = _load_monitor_config(db, config)
        if not config:
            return None

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
            return await _record_monitor_failure(
                bot,
                db,
                config,
                result,
                "review_tool",
                notify_user=notify_user,
                persist_state=persist_state,
            )

        if not persist_state:
            return result

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
            delivery_chat_id = _resolve_monitor_delivery_chat_id(db, user, "reviews")
            if notify_user and delivery_chat_id:
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
        return result
    except Exception as exc:
        db.rollback()
        logger.error("Reviews monitor failed for config %s: %s", config.id, exc, exc_info=True)
        return None
    finally:
        db.close()


async def _run_monitors(bot: Bot, *, notify_user: bool = True, persist_state: bool = True) -> None:
    db = get_db_session()
    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        configs = db.query(DataAgentMonitorConfig).filter(DataAgentMonitorConfig.is_active == True).all()
        logger.info("Running data-agent monitors: %s active configs", len(configs))

        for item in configs:
            if not _is_within_active_window(item, now):
                continue
            if not _is_monitor_due(item, now):
                continue

            if item.monitor_type == "blanks":
                await _run_blanks_monitor(bot, item, notify_user=notify_user, persist_state=persist_state)
            elif item.monitor_type == "stoplist":
                await _run_stoplist_monitor(bot, item, notify_user=notify_user, persist_state=persist_state)
            elif item.monitor_type == "reviews":
                await _run_reviews_monitor(bot, item, notify_user=notify_user, persist_state=persist_state)
    finally:
        db.close()


def start_data_agent_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    bot = Bot(token=BOT_TOKEN)
    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _scheduler.add_job(_run_monitors, "cron", minute=0, args=[bot], id="data_agent_monitors", replace_existing=True)
    _scheduler.start()
    logger.info("Data-agent monitor scheduler started with hourly cron at minute 0")


def stop_data_agent_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
