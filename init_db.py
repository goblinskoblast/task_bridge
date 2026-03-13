"""
Скрипт инициализации базы данных TaskBridge для Supabase PostgreSQL

Этот скрипт создает все необходимые таблицы в базе данных.
Запускать один раз после настройки Supabase.

Использование:
    python init_db.py
"""

import sys
import logging
from sqlalchemy import text

from db.database import sync_engine, init_db
from db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_connection():
    """Проверка подключения к базе данных"""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"✅ Подключение к PostgreSQL успешно!")
            logger.info(f"📊 Версия PostgreSQL: {version}")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к базе данных: {e}")
        return False


def create_tables():
    """Создание всех таблиц"""
    try:
        logger.info("📝 Начинаем создание таблиц...")

        # Используем встроенную функцию init_db
        init_db()

        logger.info("✅ Все таблицы успешно созданы!")

        # Выводим список созданных таблиц
        with sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = result.fetchall()

            logger.info(f"\n📋 Созданные таблицы ({len(tables)}):")
            for table in tables:
                logger.info(f"   - {table[0]}")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка при создании таблиц: {e}")
        return False


def verify_tables():
    """Проверка созданных таблиц"""
    expected_tables = [
        'users',
        'chats',
        'messages',
        'categories',
        'tasks',
        'pending_tasks',
        'task_assignees',
        'task_files',
        'comments',
        'email_accounts',
        'email_messages'
    ]

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
            existing_tables = [row[0] for row in result.fetchall()]

        missing_tables = [t for t in expected_tables if t not in existing_tables]

        if missing_tables:
            logger.warning(f"⚠️  Отсутствуют таблицы: {', '.join(missing_tables)}")
            return False
        else:
            logger.info("✅ Все ожидаемые таблицы присутствуют!")
            return True

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке таблиц: {e}")
        return False


def main():
    """Основная функция"""
    logger.info("🚀 Инициализация базы данных TaskBridge")
    logger.info("=" * 60)

    # Шаг 1: Проверка подключения
    logger.info("\n1️⃣  Проверка подключения к базе данных...")
    if not test_connection():
        logger.error("\n❌ Не удалось подключиться к базе данных. Проверьте DATABASE_URL в .env файле")
        sys.exit(1)

    # Шаг 2: Создание таблиц
    logger.info("\n2️⃣  Создание таблиц...")
    if not create_tables():
        logger.error("\n❌ Ошибка при создании таблиц")
        sys.exit(1)

    # Шаг 3: Проверка таблиц
    logger.info("\n3️⃣  Проверка созданных таблиц...")
    if not verify_tables():
        logger.warning("\n⚠️  Не все таблицы были созданы")

    logger.info("\n" + "=" * 60)
    logger.info("🎉 Инициализация базы данных завершена успешно!")
    logger.info("\n📝 Следующие шаги:")
    logger.info("   1. Запустите бота: python main.py")
    logger.info("   2. Используйте /start в Telegram для начала работы")
    logger.info("   3. Добавьте бота в групповые чаты для управления задачами")


if __name__ == "__main__":
    main()
