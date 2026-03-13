"""
Миграция базы данных для версии 2.0
Добавляет:
- Таблицу task_assignees для множественных исполнителей
- Поле created_by в таблицу tasks
- Поле assignee_usernames в таблицу pending_tasks
"""
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "taskbridge.db"


def migrate_database():
    """Применяет миграцию к существующей базе данных"""
    logger.info(f"Starting migration for database: {DB_PATH}")

    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        return False

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    try:
        # Проверяем, существует ли уже таблица task_assignees
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='task_assignees'
        """)
        if cursor.fetchone():
            logger.info("✓ Table task_assignees already exists")
        else:
            # Создаем таблицу task_assignees
            cursor.execute("""
                CREATE TABLE task_assignees (
                    task_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (task_id, user_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            logger.info("✓ Created table task_assignees")

        # Проверяем, существует ли поле created_by в tasks
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'created_by' not in columns:
            # Добавляем поле created_by
            cursor.execute("""
                ALTER TABLE tasks ADD COLUMN created_by INTEGER
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_created_by ON tasks(created_by)
            """)
            logger.info("✓ Added column created_by to tasks table")
        else:
            logger.info("✓ Column created_by already exists in tasks table")

        # Мигрируем существующие данные из assigned_to в task_assignees
        cursor.execute("""
            SELECT id, assigned_to FROM tasks WHERE assigned_to IS NOT NULL
        """)
        tasks_with_assignees = cursor.fetchall()

        migrated_count = 0
        for task_id, user_id in tasks_with_assignees:
            # Проверяем, не добавлена ли уже эта связь
            cursor.execute("""
                SELECT 1 FROM task_assignees WHERE task_id = ? AND user_id = ?
            """, (task_id, user_id))

            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO task_assignees (task_id, user_id)
                    VALUES (?, ?)
                """, (task_id, user_id))
                migrated_count += 1

        logger.info(f"✓ Migrated {migrated_count} task assignments to task_assignees table")

        # Проверяем поле assignee_usernames в pending_tasks
        cursor.execute("PRAGMA table_info(pending_tasks)")
        pending_columns = [col[1] for col in cursor.fetchall()]

        if 'assignee_usernames' not in pending_columns:
            # Добавляем поле assignee_usernames
            cursor.execute("""
                ALTER TABLE pending_tasks ADD COLUMN assignee_usernames TEXT
            """)
            logger.info("✓ Added column assignee_usernames to pending_tasks table")
        else:
            logger.info("✓ Column assignee_usernames already exists in pending_tasks table")

        # Сохраняем изменения
        conn.commit()
        logger.info("✅ Migration completed successfully!")
        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    success = migrate_database()
    if success:
        print("\n✅ Database migration completed successfully!")
    else:
        print("\n❌ Database migration failed. Check the logs for details.")
