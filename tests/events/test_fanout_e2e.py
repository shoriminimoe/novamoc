from __future__ import annotations

from typing import TYPE_CHECKING

from tests.events._http_helpers import (
    DEFAULT_HLC,
    create_asset,
    create_asset_type,
    event_envelope,
)

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


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
