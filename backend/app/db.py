from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.config import get_settings


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_async_engine(
        database_url,
        pool_pre_ping=not database_url.startswith("sqlite"),
        connect_args=connect_args,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


engine, SessionFactory = create_engine_and_session(get_settings().database_url)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session

