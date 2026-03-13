"""
Migration: Rename imap_password_encrypted to imap_password
"""
import logging
from sqlalchemy import text
from db.database import sync_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Переименовываем колонку imap_password_encrypted в imap_password"""

    with sync_engine.connect() as connection:
        try:
            # Проверяем существует ли старая колонка
            result = connection.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'email_accounts'
                AND column_name = 'imap_password_encrypted'
            """))

            if result.fetchone():
                logger.info("Found old column 'imap_password_encrypted', renaming to 'imap_password'...")

                # Переименовываем колонку
                connection.execute(text("""
                    ALTER TABLE email_accounts
                    RENAME COLUMN imap_password_encrypted TO imap_password
                """))

                connection.commit()
                logger.info("✅ Column renamed successfully!")
            else:
                logger.info("Column 'imap_password_encrypted' not found, checking for 'imap_password'...")

                # Проверяем есть ли уже новая колонка
                result = connection.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'email_accounts'
                    AND column_name = 'imap_password'
                """))

                if result.fetchone():
                    logger.info("✅ Column 'imap_password' already exists, migration not needed")
                else:
                    logger.error("❌ Neither column found! Database may be in inconsistent state")

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            connection.rollback()
            raise


if __name__ == "__main__":
    logger.info("Starting migration...")
    migrate()
    logger.info("Migration completed!")
