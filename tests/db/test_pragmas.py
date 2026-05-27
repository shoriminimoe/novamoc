"""Tests for the SQLite per-driver options registration (``db._pragmas``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.config import DatabaseSettings, Settings
from novamoc.db.config import build_alchemy_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.no_tenant
async def test_wal_mode_set_on_file_backed_sqlite(tmp_path: Path) -> None:
    """A fresh file-backed SQLite uses WAL after the first connection."""
    settings = Settings(
        db=DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path / 'wal.sqlite'}")
    )
    cfg = build_alchemy_config(settings)
    engine = cfg.get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA journal_mode")
            mode = result.scalar()
        assert mode == "wal"
    finally:
        await engine.dispose()


@pytest.mark.no_tenant
async def test_in_memory_sqlite_unaffected() -> None:
    """In-memory SQLite reports ``memory`` mode; the pragma is a no-op."""
    settings = Settings(db=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"))
    cfg = build_alchemy_config(settings)
    engine = cfg.get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA journal_mode")
            mode = result.scalar()
        assert mode == "memory"
    finally:
        await engine.dispose()
