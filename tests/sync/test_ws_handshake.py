from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_hello_handshake_returns_welcome(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        welcome = ws.receive_json()
    assert welcome == {"type": "welcome", "server_seq": 0, "schema_version": 0}


async def test_welcome_reflects_current_schema_version(client: AsyncTestClient) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(uuid4()),
            "payload": {"name": f"Truck-{uuid4()}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text

    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        welcome = ws.receive_json()
    assert welcome["schema_version"] == 1


async def test_idle_loop_ignores_malformed_frame(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"
        # A non-JSON text frame mid-stream must be ignored, not fatal.
        ws.send_text("this is not json")
        # The loop is still alive: a following ping still gets a pong.
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
