

import logging
from db.database import init_db, get_db_session
from bot.handlers import init_default_categories

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Инициализация базы данных"""
    try:
        logger.info("Инициализация базы данных...")
        
        # Создаем все таблицы
        init_db()
        logger.info("✓ Таблицы созданы")
        
        # Инициализируем категории по умолчанию
        db = get_db_session()
        try:
            init_default_categories(db)
            logger.info("✓ Категории инициализированы")
        finally:
            db.close()
        
        logger.info("\n✅ База данных успешно инициализирована!")
        logger.info("Теперь можно запустить бота: python main.py")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации: {e}")
        raise


if __name__ == "__main__":
    main()

