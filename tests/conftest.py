"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from advanced_alchemy.base import metadata_registry
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Importing the models registers their tables on the shared metadata registry.
import novamoc.db.models  # noqa: F401


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        try:
            yield s
        finally:
            await s.rollback()
