from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


STARTUP_LOCK_ID = 727274


@asynccontextmanager
async def startup_lock():
    """Serialise startup work (table creation, seeding) across replicas.

    With several pods starting at once on an empty database, concurrent
    create_all calls can collide. A Postgres advisory lock makes them take turns.
    No-op on other databases (SQLite is single-process anyway).
    """
    if engine.dialect.name != "postgresql":
        yield
        return

    async with engine.connect() as conn:
        # Autocommit: the lock is session-level and must not sit inside a transaction.
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": STARTUP_LOCK_ID})
        try:
            yield
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": STARTUP_LOCK_ID})
