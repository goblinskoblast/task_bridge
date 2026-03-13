"""
Database Migration: Remove Deprecated Fields
Safely removes deprecated fields from Task and PendingTask models
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_path() -> str:
    """Get the database file path"""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "sqlite:///taskbridge.db")

    # Extract file path from sqlite URL
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "")
    else:
        return "taskbridge.db"


def backup_database(db_path: str) -> str:
    """Create a backup of the database"""
    import shutil

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"

    if Path(db_path).exists():
        shutil.copy2(db_path, backup_path)
        logger.info(f"✅ Database backed up to: {backup_path}")
        return backup_path
    else:
        logger.warning(f"⚠️  Database file not found: {db_path}")
        return None


def check_orphaned_data(conn: sqlite3.Connection) -> dict:
    """Check for orphaned data in deprecated fields"""
    cursor = conn.cursor()

    results = {}

    # Check Task.assigned_to
    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE assigned_to IS NOT NULL
    """)
    results['tasks_with_assigned_to'] = cursor.fetchone()[0]

    # Check if any of those are orphaned (not in task_assignees)
    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks t
        WHERE t.assigned_to IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM task_assignees ta
            WHERE ta.task_id = t.id AND ta.user_id = t.assigned_to
        )
    """)
    results['orphaned_assigned_to'] = cursor.fetchone()[0]

    # Check PendingTask.assignee_username
    cursor.execute("""
        SELECT COUNT(*)
        FROM pending_tasks
        WHERE assignee_username IS NOT NULL
        AND (assignee_usernames IS NULL OR assignee_usernames = '[]')
    """)
    results['orphaned_assignee_username'] = cursor.fetchone()[0]

    return results


def migrate_orphaned_data(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """Migrate any orphaned data to new fields"""
    cursor = conn.cursor()
    migrated = 0

    # Migrate Task.assigned_to to task_assignees
    cursor.execute("""
        SELECT t.id, t.assigned_to
        FROM tasks t
        WHERE t.assigned_to IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM task_assignees ta
            WHERE ta.task_id = t.id AND ta.user_id = t.assigned_to
        )
    """)

    orphaned_tasks = cursor.fetchall()

    if orphaned_tasks:
        logger.info(f"Found {len(orphaned_tasks)} orphaned task assignments")

        if not dry_run:
            for task_id, user_id in orphaned_tasks:
                cursor.execute("""
                    INSERT INTO task_assignees (task_id, user_id)
                    VALUES (?, ?)
                """, (task_id, user_id))
                migrated += 1

            logger.info(f"✅ Migrated {migrated} orphaned task assignments")

    # Migrate PendingTask.assignee_username to assignee_usernames
    cursor.execute("""
        SELECT id, assignee_username
        FROM pending_tasks
        WHERE assignee_username IS NOT NULL
        AND (assignee_usernames IS NULL OR assignee_usernames = '[]')
    """)

    orphaned_pending = cursor.fetchall()

    if orphaned_pending:
        logger.info(f"Found {len(orphaned_pending)} orphaned pending task assignees")

        if not dry_run:
            for pending_id, username in orphaned_pending:
                import json
                cursor.execute("""
                    UPDATE pending_tasks
                    SET assignee_usernames = ?
                    WHERE id = ?
                """, (json.dumps([username]), pending_id))
                migrated += 1

            logger.info(f"✅ Migrated {migrated} orphaned pending task assignees")

    return migrated


def drop_deprecated_columns(conn: sqlite3.Connection, dry_run: bool = True):
    """Drop deprecated columns from tables"""
    cursor = conn.cursor()

    if dry_run:
        logger.info("DRY RUN: Would drop the following columns:")
        logger.info("  - tasks.assigned_to")
        logger.info("  - pending_tasks.assignee_username")
        return

    logger.info("Dropping deprecated columns...")

    # SQLite doesn't support DROP COLUMN directly, need to recreate tables
    # Step 1: Create new tables without deprecated columns

    # Get existing Task table schema
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'")
    old_schema = cursor.fetchone()[0]

    # Create temporary table for tasks
    cursor.execute("""
        CREATE TABLE tasks_new (
            id INTEGER PRIMARY KEY,
            message_id INTEGER,
            category_id INTEGER,
            created_by INTEGER,
            title VARCHAR(500) NOT NULL,
            description TEXT,
            status VARCHAR(50) DEFAULT 'pending',
            priority VARCHAR(50) DEFAULT 'normal',
            due_date DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (category_id) REFERENCES categories(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # Copy data from old table (excluding assigned_to)
    cursor.execute("""
        INSERT INTO tasks_new
        (id, message_id, category_id, created_by, title, description, status, priority, due_date, created_at, updated_at)
        SELECT id, message_id, category_id, created_by, title, description, status, priority, due_date, created_at, updated_at
        FROM tasks
    """)

    # Drop old table and rename new one
    cursor.execute("DROP TABLE tasks")
    cursor.execute("ALTER TABLE tasks_new RENAME TO tasks")

    logger.info("✅ Dropped tasks.assigned_to")

    # Create temporary table for pending_tasks
    cursor.execute("""
        CREATE TABLE pending_tasks_new (
            id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            chat_id BIGINT NOT NULL,
            created_by_id INTEGER NOT NULL,
            title VARCHAR(500) NOT NULL,
            description TEXT,
            assignee_usernames JSON,
            due_date DATETIME,
            priority VARCHAR(50) DEFAULT 'normal',
            status VARCHAR(50) DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (created_by_id) REFERENCES users(id)
        )
    """)

    # Copy data from old table (excluding assignee_username)
    cursor.execute("""
        INSERT INTO pending_tasks_new
        (id, message_id, chat_id, created_by_id, title, description, assignee_usernames, due_date, priority, status, created_at)
        SELECT id, message_id, chat_id, created_by_id, title, description, assignee_usernames, due_date, priority, status, created_at
        FROM pending_tasks
    """)

    # Drop old table and rename new one
    cursor.execute("DROP TABLE pending_tasks")
    cursor.execute("ALTER TABLE pending_tasks_new RENAME TO pending_tasks")

    logger.info("✅ Dropped pending_tasks.assignee_username")


def verify_migration(conn: sqlite3.Connection) -> bool:
    """Verify migration was successful"""
    cursor = conn.cursor()

    # Check that deprecated columns are gone
    cursor.execute("PRAGMA table_info(tasks)")
    task_columns = [row[1] for row in cursor.fetchall()]

    cursor.execute("PRAGMA table_info(pending_tasks)")
    pending_columns = [row[1] for row in cursor.fetchall()]

    if 'assigned_to' in task_columns:
        logger.error("❌ tasks.assigned_to still exists!")
        return False

    if 'assignee_username' in pending_columns:
        logger.error("❌ pending_tasks.assignee_username still exists!")
        return False

    # Check data integrity
    cursor.execute("SELECT COUNT(*) FROM tasks")
    task_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM pending_tasks")
    pending_count = cursor.fetchone()[0]

    logger.info(f"✅ Verification passed:")
    logger.info(f"   - tasks: {task_count} rows")
    logger.info(f"   - pending_tasks: {pending_count} rows")
    logger.info(f"   - Deprecated columns removed")

    return True


def run_migration(dry_run: bool = True):
    """Run the complete migration process"""
    logger.info("=" * 60)
    logger.info("MIGRATION: Remove Deprecated Fields")
    logger.info("=" * 60)

    if dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made")
    else:
        logger.info("⚠️  LIVE MODE - Database will be modified")

    logger.info("")

    # Get database path
    db_path = get_db_path()
    logger.info(f"Database: {db_path}")

    # Backup database
    if not dry_run:
        backup_path = backup_database(db_path)
        if not backup_path:
            logger.error("❌ Cannot proceed without database backup")
            return

    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Check for orphaned data
        logger.info("\n📊 Checking for orphaned data...")
        orphaned = check_orphaned_data(conn)

        logger.info(f"   - Tasks with assigned_to: {orphaned['tasks_with_assigned_to']}")
        logger.info(f"   - Orphaned assigned_to: {orphaned['orphaned_assigned_to']}")
        logger.info(f"   - Orphaned assignee_username: {orphaned['orphaned_assignee_username']}")

        # Migrate orphaned data if found
        if orphaned['orphaned_assigned_to'] > 0 or orphaned['orphaned_assignee_username'] > 0:
            logger.info("\n🔄 Migrating orphaned data...")
            migrated = migrate_orphaned_data(conn, dry_run=dry_run)

            if not dry_run:
                conn.commit()
                logger.info(f"✅ Migrated {migrated} records")
        else:
            logger.info("✅ No orphaned data found")

        # Drop deprecated columns
        logger.info("\n🗑️  Removing deprecated columns...")
        drop_deprecated_columns(conn, dry_run=dry_run)

        if not dry_run:
            conn.commit()

            # Verify migration
            logger.info("\n✔️  Verifying migration...")
            if verify_migration(conn):
                logger.info("\n✅ MIGRATION COMPLETED SUCCESSFULLY!")
            else:
                logger.error("\n❌ MIGRATION VERIFICATION FAILED!")
                logger.error(f"Please restore from backup: {backup_path}")
        else:
            logger.info("\n🔍 DRY RUN COMPLETE - Run with dry_run=False to apply changes")

    except Exception as e:
        logger.error(f"\n❌ MIGRATION FAILED: {e}", exc_info=True)
        conn.rollback()
        logger.error("Changes have been rolled back")

        if not dry_run:
            logger.error(f"Please restore from backup: {backup_path}")

    finally:
        conn.close()
        logger.info("\n" + "=" * 60)


if __name__ == "__main__":
    import sys

    # Parse command line arguments
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        dry_run = False

    run_migration(dry_run=dry_run)

    if dry_run:
        print("\nTo execute the migration, run: python db/migrate_remove_deprecated_fields.py --execute")
