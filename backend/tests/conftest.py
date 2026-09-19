from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.db import create_engine_and_session
from backend.app.models import Base


@pytest.fixture
async def session_factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    database_path = (tmp_path / "test.db").as_posix()
    engine, factory = create_engine_and_session(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()
