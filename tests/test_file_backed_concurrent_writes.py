"""File-backed SQLite + request-scoped writer vs SessionMiddleware writer.

The default ``settings`` / ``app`` fixtures in :mod:`tests.conftest`
back the test app with an in-memory ``StaticPool`` SQLite database, so
every ``AsyncSession`` opened from the same ``SQLAlchemyAsyncConfig``
shares one underlying connection and cannot self-deadlock on the
SQLite writer slot. Production (``just serve`` against
``sqlite+aiosqlite:///novamoc.sqlite``) uses the default
``AsyncAdaptedQueuePool`` and a real on-disk file, so the
request-scoped session a handler writes through and a second
``AsyncSession`` opened by the stock ``SQLAlchemyAsyncSessionBackend``
during ``http.response.start`` would land on *different* aiosqlite
connections and contend for SQLite's single writer slot.

This module reproduces that path under ``AsyncTestClient`` (no
granian, no fork) and is the regression gate for novamoc#123. The
fix it covers is the request-scoped session backend: with one
writer per request, the single-writer model is never approached.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.alembic.commands import AlembicCommands
from advanced_alchemy.base import metadata_registry
from litestar.testing import AsyncTestClient

from novamoc.asgi import create_app
from novamoc.config import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    ServerSettings,
    Settings,
)
from novamoc.db.config import build_alchemy_config
from tests._constants import DEV_PASSWORD, DEV_USERNAME
from tests.conftest import seed_dev_admin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from litestar import Litestar


@pytest.fixture
def file_settings(tmp_path: Path) -> Settings:
    """Production-shaped ``Settings`` against a tmp-dir on-disk SQLite file."""
    db_path = tmp_path / "novamoc.sqlite"
    return Settings(
        db=DatabaseSettings(
            url=f"sqlite+aiosqlite:///{db_path}",
            static_pool=False,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test"),
        auth=AuthSettings(
            argon2_time_cost=1,
            argon2_memory_cost_kib=8192,
            argon2_parallelism=1,
            session_cookie_secure=False,
        ),
    )


@pytest.fixture
async def file_app(file_settings: Settings) -> AsyncIterator[Litestar]:
    """Mirror of :func:`tests.conftest.app` but on the file-backed settings.

    Builds the engine, runs ``metadata.create_all`` against it, stamps
    Alembic HEAD off-thread so the startup gate accepts the database,
    then hands the populated config to ``create_app``. The conftest
    ``app`` fixture pins ``StaticPool`` and masks #123; this fixture
    keeps the default queue pool, which is the condition the bug
    needs.
    """
    alchemy_config = build_alchemy_config(file_settings)
    engine = alchemy_config.get_engine()
    async with engine.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    await asyncio.to_thread(AlembicCommands(alchemy_config).stamp, "head")
    try:
        yield create_app(settings=file_settings, alchemy_config=alchemy_config)
    finally:
        await engine.dispose()


async def test_post_schema_succeeds_against_file_backed_db(file_app: Litestar) -> None:
    """Two writers in one request must coexist on a file-backed SQLite DB.

    ``POST /schema`` triggers an ``asset_types`` INSERT through the
    request-scoped session (committed by the ``autocommit``
    before-send handler). At ``http.response.start`` time the
    ``SessionMiddleware`` upserts the ``sessions`` row. Pre-fix the
    upsert went through a *second* session opened via
    ``alchemy_config.get_session()`` and contended with the
    request-scoped one for the SQLite writer slot, raising
    ``OperationalError: database is locked`` (or
    ``attempt to write a readonly database`` under granian timing).
    Post-fix the backend folds the upsert into the request session,
    so only one writer exists per request.
    """
    async with AsyncTestClient(file_app) as client:
        await seed_dev_admin(file_app)

        login = await client.post(
            "/auth/login",
            json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
        )
        assert login.status_code == 204, login.text

        write = await client.post(
            "/schema",
            json={
                "type": "create_asset_type",
                "entity_id": str(uuid.uuid4()),
                "payload": {"name": "Pump"},
            },
        )
        assert write.status_code in (200, 201), write.text
        body = write.json()
        assert body["outcome"] == "created"
        assert body["schema_version"] >= 1
