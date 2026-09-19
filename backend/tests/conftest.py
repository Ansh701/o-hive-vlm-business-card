from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.db import create_engine_and_session
from backend.app.models import Base


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine, factory = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()
