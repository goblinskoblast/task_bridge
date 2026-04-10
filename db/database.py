from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine, inspect, text
from config import DATABASE_URL
from db.models import Base


def get_async_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    return url


if "postgresql" in DATABASE_URL:
    sync_engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True
    )
elif "sqlite" in DATABASE_URL:
    sync_engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False}
    )
else:
    sync_engine = create_engine(
        "sqlite:///taskbridge.db",
        echo=False,
        connect_args={"check_same_thread": False}
    )


ASYNC_DATABASE_URL = get_async_database_url(DATABASE_URL)

if "postgresql" in DATABASE_URL:
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True
    )
else:
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False}
    )


AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def init_db():
    Base.metadata.create_all(bind=sync_engine)
    _ensure_task_columns()
    _ensure_data_agent_profile_columns()
    _ensure_data_agent_session_columns()
    _ensure_saved_point_columns()


def _ensure_task_columns():
    inspector = inspect(sync_engine)
    column_names = {column["name"] for column in inspector.get_columns("tasks")}
    datetime_type = "TIMESTAMP" if sync_engine.dialect.name == "postgresql" else "DATETIME"
    alter_statements = []

    if "reminder_interval_hours" not in column_names:
        alter_statements.append("ALTER TABLE tasks ADD COLUMN reminder_interval_hours INTEGER")
    if "last_assignee_reminder_sent_at" not in column_names:
        alter_statements.append(
            f"ALTER TABLE tasks ADD COLUMN last_assignee_reminder_sent_at {datetime_type}"
        )
    if "last_creator_reminder_sent_at" not in column_names:
        alter_statements.append(
            f"ALTER TABLE tasks ADD COLUMN last_creator_reminder_sent_at {datetime_type}"
        )

    if not alter_statements:
        return

    with sync_engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def _ensure_data_agent_profile_columns():
    inspector = inspect(sync_engine)
    if "data_agent_profiles" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("data_agent_profiles")}
    bigint_type = "BIGINT" if sync_engine.dialect.name == "postgresql" else "INTEGER"
    alter_statements = []

    if "default_report_chat_id" not in column_names:
        alter_statements.append(
            f"ALTER TABLE data_agent_profiles ADD COLUMN default_report_chat_id {bigint_type}"
        )
    if "default_report_chat_title" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_profiles ADD COLUMN default_report_chat_title VARCHAR(500)"
        )
    if "reviews_report_chat_id" not in column_names:
        alter_statements.append(
            f"ALTER TABLE data_agent_profiles ADD COLUMN reviews_report_chat_id {bigint_type}"
        )
    if "reviews_report_chat_title" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_profiles ADD COLUMN reviews_report_chat_title VARCHAR(500)"
        )
    if "stoplist_report_chat_id" not in column_names:
        alter_statements.append(
            f"ALTER TABLE data_agent_profiles ADD COLUMN stoplist_report_chat_id {bigint_type}"
        )
    if "stoplist_report_chat_title" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_profiles ADD COLUMN stoplist_report_chat_title VARCHAR(500)"
        )
    if "blanks_report_chat_id" not in column_names:
        alter_statements.append(
            f"ALTER TABLE data_agent_profiles ADD COLUMN blanks_report_chat_id {bigint_type}"
        )
    if "blanks_report_chat_title" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_profiles ADD COLUMN blanks_report_chat_title VARCHAR(500)"
        )

    if not alter_statements:
        return

    with sync_engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def _ensure_data_agent_session_columns():
    inspector = inspect(sync_engine)
    if "data_agent_sessions" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("data_agent_sessions")}
    alter_statements = []

    if "last_trace_id" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_sessions ADD COLUMN last_trace_id VARCHAR(64)"
        )
    if "last_debug_summary" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_sessions ADD COLUMN last_debug_summary TEXT"
        )
    if "last_debug_payload" not in column_names:
        alter_statements.append(
            "ALTER TABLE data_agent_sessions ADD COLUMN last_debug_payload JSON"
        )

    if not alter_statements:
        return

    with sync_engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def _ensure_saved_point_columns():
    inspector = inspect(sync_engine)
    if "saved_points" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("saved_points")}
    integer_type = "INTEGER"
    boolean_type = "BOOLEAN" if sync_engine.dialect.name == "postgresql" else "INTEGER"
    alter_statements = []

    if "system_id" not in column_names:
        alter_statements.append(
            f"ALTER TABLE saved_points ADD COLUMN system_id {integer_type}"
        )
    if "report_delivery_enabled" not in column_names:
        default_literal = "FALSE" if sync_engine.dialect.name == "postgresql" else "0"
        alter_statements.append(
            f"ALTER TABLE saved_points ADD COLUMN report_delivery_enabled {boolean_type} DEFAULT {default_literal}"
        )

    if not alter_statements:
        return

    with sync_engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


async def get_async_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    return SessionLocal()


def get_async_session() -> AsyncSession:
    return AsyncSessionLocal()
