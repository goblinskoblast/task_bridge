from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
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
    """Инициализация базы данных - создание всех таблиц (синхронно)"""
    Base.metadata.create_all(bind=sync_engine)


async def get_async_db():
    """Получение асинхронной сессии базы данных"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_db():
    """Получение синхронной сессии (для FastAPI endpoints)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Получение синхронного объекта сессии (для совместимости)"""
    return SessionLocal()


def get_async_session() -> AsyncSession:
    """Получение асинхронной сессии (для прямого использования)"""
    return AsyncSessionLocal()
