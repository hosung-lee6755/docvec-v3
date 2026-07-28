from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    # Default pool_size=5/max_overflow=10 exhausted under a batch of ~14
    # documents processing concurrently — each in-flight block execution
    # holds its own connection (문서 파싱 고도화 회고, 2026-07-23: observed
    # `QueuePool limit of size 5 overflow 10 reached` failing a real batch
    # upload's pii_detect block). Postgres max_connections=100 confirmed
    # before sizing this.
    pool_size=15,
    max_overflow=15,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=15, max_overflow=15)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


async def get_db():
    async with async_session_maker() as session:
        yield session


def get_sync_db() -> Session:
    return SyncSessionLocal()
