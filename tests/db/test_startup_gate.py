"""Tests for the alembic-revision startup gate (``db._startup``)."""

from __future__ import annotations

import asyncio

import pytest
from advanced_alchemy.alembic.commands import AlembicCommands

from novamoc.config import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    ServerSettings,
    Settings,
)
from novamoc.db._startup import AlembicRevisionMismatchError, assert_alembic_at_head
from novamoc.db.config import build_alchemy_config


def _settings() -> Settings:
    return Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:///:memory:",
            static_pool=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test"),
        auth=AuthSettings(session_cookie_secure=False),
    )


@pytest.mark.no_tenant
async def test_gate_raises_when_alembic_version_table_missing() -> None:
    """Empty database -> startup must refuse with both remediation paths."""
    cfg = build_alchemy_config(_settings())
    engine = cfg.get_engine()
    try:
        with pytest.raises(AlembicRevisionMismatchError) as exc_info:
            await assert_alembic_at_head(cfg)
        message = str(exc_info.value)
        # Names ``just db-init`` for dev and the raw ``alchemy upgrade head``
        # invocation for production init containers without ``just``.
        assert "just db-init" in message
        assert "alchemy" in message
        assert "upgrade head" in message
    finally:
        await engine.dispose()


@pytest.mark.no_tenant
async def test_gate_passes_when_db_at_head() -> None:
    """Stamped database -> startup is silent."""
    cfg = build_alchemy_config(_settings())
    engine = cfg.get_engine()
    try:
        await asyncio.to_thread(AlembicCommands(cfg).stamp, "head")
        await assert_alembic_at_head(cfg)
    finally:
        await engine.dispose()


@pytest.mark.no_tenant
async def test_gate_raises_when_db_unreachable() -> None:
    """Connection failure -> friendly error rather than raw SQLAlchemy trace."""
    # A path under a directory that doesn't exist forces SQLite to
    # raise ``unable to open database file`` on connect.
    settings = Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:////nonexistent/dir/should-not-resolve.sqlite",
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test"),
        auth=AuthSettings(session_cookie_secure=False),
    )
    cfg = build_alchemy_config(settings)
    engine = cfg.get_engine()
    try:
        with pytest.raises(AlembicRevisionMismatchError) as exc_info:
            await assert_alembic_at_head(cfg)
        message = str(exc_info.value)
        assert "Could not connect" in message
        assert "just db-init" in message
    finally:
        await engine.dispose()
