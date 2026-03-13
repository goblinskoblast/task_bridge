"""
Временный файл для запуска только бота без веб-приложения
Используется для тестирования OpenClaw интеграции
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import BOT_TOKEN
from bot.handlers import router, init_default_categories
from bot.email_registration import router as email_router
from bot.support_handlers import router as support_router
from bot.reminders import start_reminder_scheduler, stop_reminder_scheduler
from db.database import init_db, get_db_session


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def set_bot_commands(bot: Bot):
    """Устанавливает меню команд бота"""
    commands = [
        BotCommand(command="start", description="🚀 Начать работу с ботом"),
        BotCommand(command="panel", description="📱 Открыть панель задач"),
        BotCommand(command="support", description="💬 Чат поддержки"),
        BotCommand(command="help", description="❓ Справка и инструкции")
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    logger.info("Bot commands menu set successfully")


async def start_bot_polling():
    """Запуск бота в режиме polling (для разработки)"""

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

    # Регистрируем роутеры (email_router и support_router ПЕРВЫМИ для приоритета FSM)
    dp.include_router(email_router)
    dp.include_router(support_router)
    dp.include_router(router)

    # Устанавливаем меню команд
    await set_bot_commands(bot)

    logger.info("Bot started in polling mode (BOT ONLY - no webapp)")
    logger.info("Ready for testing OpenClaw integration!")

    start_reminder_scheduler(bot)
    logger.info("Reminder scheduler started")

    try:
        await dp.start_polling(bot, handle_as_tasks=False)
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")
    finally:
        stop_reminder_scheduler()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(start_bot_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
