from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig, SQLAlchemyPlugin
from litestar.testing import AsyncTestClient

from novamoc.asgi import create_app
from tests._constants import DEV_TENANT_ID
from tests.events._http_helpers import (
    DEFAULT_HLC,
    create_asset,
    create_asset_type,
    event_envelope,
)

if TYPE_CHECKING:
    from litestar import Litestar

    from novamoc.config import Settings


class _StubBroadcaster:
    def __init__(self) -> None:
        self.notified = 0

    def notify(self) -> None:
        self.notified += 1


async def test_accepted_batch_signals_broadcaster(
    client: AsyncTestClient, app: Litestar
) -> None:
    stub = _StubBroadcaster()
    app.state.event_broadcaster = stub
    type_id, schema_version = await create_asset_type(client)
    await create_asset(
        client, type_id=type_id, schema_version=schema_version, hlc=DEFAULT_HLC
    )  # asserts 202 (accepted) internally
    assert stub.notified == 1


async def test_rejected_batch_does_not_signal(
    client: AsyncTestClient, app: Litestar
) -> None:
    stub = _StubBroadcaster()
    app.state.event_broadcaster = stub
    type_id, schema_version = await create_asset_type(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version + 1,  # != current → batch rejected
            "events": [event_envelope(type_id=type_id)],
        },
    )
    assert resp.status_code == 409, resp.text  # schema_version_stale (batch-level)
    assert stub.notified == 0


async def test_event_reaches_subscribed_socket(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, schema_version = await create_asset_type(client)
    with await client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"

        await create_asset(
            client, type_id=type_id, schema_version=schema_version, hlc=DEFAULT_HLC
        )
        drained = await app.state.event_broadcaster.drain_once()
        assert drained >= 1

        frame = ws.receive_json()
    assert frame["type"] == "event"
    assert frame["body"]["event"] == "created"


async def test_broadcaster_task_runs_when_enabled(
    settings: Settings, app: Litestar
) -> None:
    # reuse the app fixture's already-migrated engine
    plugin = app.plugins.get(SQLAlchemyPlugin)
    cfg = next(c for c in plugin.config if isinstance(c, SQLAlchemyAsyncConfig))
    enabled = replace(settings, app=replace(settings.app, broadcaster_enabled=True))
    enabled_app = create_app(settings=enabled, alchemy_config=cfg)

    async with AsyncTestClient(enabled_app):
        task = enabled_app.state.get("broadcaster_task")
        assert isinstance(task, asyncio.Task)
        assert not task.done()
    # context exit triggers on_shutdown → the task is cancelled
    assert task.cancelled() or task.done()
