import asyncio
import logging
import os
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommandScopeDefault
from fastapi import HTTPException, Request
import uvicorn

from bot.data_agent_handlers import router as data_agent_router
from bot.handlers import init_default_categories, router
from bot.reminders import start_reminder_scheduler, stop_reminder_scheduler
from bot.support_handlers import router as support_router
from config import BOT_TOKEN, HOST, PORT, USE_WEBHOOK, WEBHOOK_PATH, WEBHOOK_URL
from db.database import get_db_session, init_db
from webapp.app import app as webapp_app
from webhook_lifecycle import build_webhook_lifespan


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_webhook_target() -> str:
    return f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"


async def set_bot_commands(bot: Bot) -> None:
    """Keep Telegram's slash-command menu hidden; /start reply buttons are the primary path."""
    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    logger.info("Bot commands menu cleared")


def build_dispatcher() -> Dispatcher:
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(support_router)
    dp.include_router(data_agent_router)
    dp.include_router(router)
    return dp


async def initialize_bot_runtime() -> Tuple[Bot, Dispatcher]:
    init_db()
    logger.info("Database initialized")

    db = get_db_session()
    try:
        init_default_categories(db)
        logger.info("Default categories initialized")
    finally:
        db.close()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    await set_bot_commands(bot)
    return bot, dp


async def close_bot_runtime(bot: Optional[Bot]) -> None:
    stop_reminder_scheduler()
    if bot is not None:
        await bot.session.close()


def configure_webhook_mode() -> None:
    if getattr(webapp_app.state, "taskbridge_webhook_configured", False):
        return

    webapp_app.state.taskbridge_webhook_configured = True
    webapp_app.state.taskbridge_bot = None
    webapp_app.state.taskbridge_dispatcher = None
    webapp_app.router.lifespan_context = build_webhook_lifespan(
        app=webapp_app,
        use_webhook=USE_WEBHOOK,
        webhook_url=WEBHOOK_URL,
        webhook_target=get_webhook_target(),
        initialize_runtime=initialize_bot_runtime,
        close_runtime=close_bot_runtime,
        start_scheduler=start_reminder_scheduler,
        logger=logger,
    )

    @webapp_app.post(WEBHOOK_PATH, include_in_schema=False)
    async def telegram_webhook(request: Request) -> dict:
        bot = getattr(webapp_app.state, "taskbridge_bot", None)
        dp = getattr(webapp_app.state, "taskbridge_dispatcher", None)
        if bot is None or dp is None:
            raise HTTPException(status_code=503, detail="Webhook runtime is not ready")

        payload = await request.json()
        response = await dp.feed_webhook_update(bot, payload, _timeout=5)
        if response is not None and hasattr(response, "model_dump"):
            return response.model_dump(exclude_none=True, by_alias=True)
        return {"ok": True}


async def start_bot_polling() -> None:
    """Run the bot in polling mode."""
    bot, dp = await initialize_bot_runtime()
    logger.info("Bot started in polling mode")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted before polling start")
    except Exception as exc:
        logger.warning("Failed to delete webhook before polling: %s", exc)

    start_reminder_scheduler(bot)
    logger.info("Reminder scheduler started")

    try:
        await dp.start_polling(
            bot,
            handle_as_tasks=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except Exception as exc:
        logger.error("Error in bot polling: %s", exc)
    finally:
        await close_bot_runtime(bot)


async def start_bot_webhook() -> None:
    configure_webhook_mode()
    web_port = int(os.environ.get("PORT", PORT))
    logger.info("Starting webhook web app on %s:%s", HOST, web_port)
    server = uvicorn.Server(uvicorn.Config(webapp_app, host=HOST, port=web_port))
    await server.serve()


def start_webapp() -> None:
    """Run the web application in a background thread."""
    port = int(os.environ.get("PORT", PORT))
    logger.info("Starting web app on %s:%s", HOST, port)
    uvicorn.run(webapp_app, host=HOST, port=port)


async def main() -> None:
    if USE_WEBHOOK:
        logger.info("Starting in webhook mode")
        await start_bot_webhook()
        return

    logger.info("Starting in polling mode")

    import threading

    webapp_thread = threading.Thread(target=start_webapp, daemon=True)
    webapp_thread.start()
    logger.info("Web app started in background thread")

    await start_bot_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
