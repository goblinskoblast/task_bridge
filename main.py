import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import BOT_TOKEN, USE_WEBHOOK, WEBHOOK_PATH, WEBHOOK_URL, HOST, PORT
from bot.handlers import router, init_default_categories
from bot.data_agent_handlers import router as data_agent_router
from bot.support_handlers import router as support_router
from bot.reminders import start_reminder_scheduler, stop_reminder_scheduler
from db.database import init_db, get_db_session
from webapp.app import app as webapp_app
import uvicorn


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def set_bot_commands(bot: Bot):
    """Устанавливает меню команд бота."""
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="panel", description="Открыть панель задач"),
        BotCommand(command="agent", description="Открыть диалог агента"),
        BotCommand(command="connect", description="Подключить систему для агента"),
        BotCommand(command="systems", description="Список систем агента"),
        BotCommand(command="support", description="Чат поддержки"),
        BotCommand(command="help", description="Справка и инструкции"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    logger.info("Bot commands menu set successfully")


async def start_bot_polling():
    """Р—Р°РїСѓСЃРє Р±РѕС‚Р° РІ СЂРµР¶РёРјРµ polling (РґР»СЏ СЂР°Р·СЂР°Р±РѕС‚РєРё)"""

    init_db()
    logger.info("Database initialized")


    db = get_db_session()
    try:
        init_default_categories(db)
        logger.info("Default categories initialized")
    finally:
        db.close()


    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј СЂРѕСѓС‚РµСЂС‹
    dp.include_router(support_router)
    dp.include_router(data_agent_router)
    dp.include_router(router)

    # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РјРµРЅСЋ РєРѕРјР°РЅРґ
    await set_bot_commands(bot)

    logger.info("Bot started in polling mode")

    # Prevent polling/webhook conflicts after redeploys.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted before polling start")
    except Exception as e:
        logger.warning(f"Failed to delete webhook before polling: {e}")

    start_reminder_scheduler(bot)
    logger.info("Reminder scheduler started")

    try:

        await dp.start_polling(bot, handle_as_tasks=False)
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")
    finally:
        stop_reminder_scheduler()
        await bot.session.close()


async def start_bot_webhook():
    init_db()
    logger.info("Database initialized")


    db = get_db_session()
    try:
        init_default_categories(db)
        logger.info("Default categories initialized")
    finally:
        db.close()


    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј СЂРѕСѓС‚РµСЂС‹
    dp.include_router(support_router)
    dp.include_router(data_agent_router)
    dp.include_router(router)

    # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РјРµРЅСЋ РєРѕРјР°РЅРґ
    await set_bot_commands(bot)

    try:

        await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
        logger.info(f"Webhook set to {WEBHOOK_URL + WEBHOOK_PATH}")


        import os
        web_port = int(os.environ.get("PORT", PORT))
        loop = asyncio.get_event_loop()
        server = uvicorn.Server(uvicorn.Config(webapp_app, host=HOST, port=web_port))
        loop.create_task(server.serve())


        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Error in bot webhook: {e}")
    finally:
        await bot.session.close()


def start_webapp():
    """Р—Р°РїСѓСЃРє РІРµР±-РїСЂРёР»РѕР¶РµРЅРёСЏ"""
    import os

    port = int(os.environ.get("PORT", PORT))
    logger.info(f"Starting web app on {HOST}:{port}")
    uvicorn.run(webapp_app, host=HOST, port=port)


async def main():

    if USE_WEBHOOK:
        logger.info("Starting in webhook mode")
        await start_bot_webhook()
    else:
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
    except Exception as e:
        logger.error(f"Fatal error: {e}")
