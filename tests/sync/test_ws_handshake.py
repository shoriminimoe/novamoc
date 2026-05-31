from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from litestar.exceptions import WebSocketDisconnect

from tests._constants import DEV_TENANT_ID, DEV_TENANT_ID_B

if TYPE_CHECKING:
    import uuid

    from litestar import Litestar
    from litestar.testing import AsyncTestClient

    from novamoc.config import Settings


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


# ---------------------------------------------------------------------------
# Task 7 — tenant mismatch closes 1008
# ---------------------------------------------------------------------------


async def test_tenant_mismatch_closes_1008(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json(
            {"type": "hello", "tenant_id": str(DEV_TENANT_ID_B), "cursor": 0}
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/tenant_mismatch.html")
        assert problem["ws_close_code"] == 1008
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1008
    assert exc_info.value.detail == "tenant_mismatch"


# ---------------------------------------------------------------------------
# Task 8 — malformed hello (1003) + negative cursor (1008)
# ---------------------------------------------------------------------------


async def test_unknown_field_closes_1003(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json(
            {
                "type": "hello",
                "tenant_id": str(DEV_TENANT_ID),
                "cursor": 0,
                "bogus": 1,
            }
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/invalid_payload_shape.html")
        assert problem["ws_close_code"] == 1003
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1003


async def test_wrong_tag_closes_1003(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json(
            {"type": "welcome", "tenant_id": str(DEV_TENANT_ID), "cursor": 0}
        )
        problem = ws.receive_json()
        assert problem["ws_close_code"] == 1003
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


async def test_negative_cursor_closes_1008(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json(
            {"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": -1}
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/invalid_payload_shape.html")
        assert problem["ws_close_code"] == 1008
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# Task 9 — handshake timeout closes 1008
# ---------------------------------------------------------------------------


async def test_handshake_timeout_closes_1008(
    client: AsyncTestClient, app: Litestar, settings: Settings
) -> None:
    app.state.settings = replace(
        settings, app=replace(settings.app, ws_handshake_timeout_seconds=0.2)
    )
    with (await client.websocket_connect("/sync/live")) as ws:
        # Send nothing; wait past the window for the server to close.
        # The server sends a problem body frame, then closes with 1008.
        problem = ws.receive_json()
        assert problem["ws_close_code"] == 1008
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1008
    assert exc_info.value.detail == "handshake_timeout"


# ---------------------------------------------------------------------------
# Task 10 — unauthenticated upgrade rejected
# ---------------------------------------------------------------------------


async def test_unauthenticated_upgrade_rejected(
    unauth_client: AsyncTestClient,
) -> None:
    # The auth middleware closes the socket before accept(), so the
    # WebSocketTestSession.__enter__() raises WebSocketDisconnect — the body
    # never executes.  Enter the session manually so pytest.raises wraps
    # only that single call.
    ws_session = await unauth_client.websocket_connect("/sync/live")
    with pytest.raises(WebSocketDisconnect):
        ws_session.__enter__()


# ---------------------------------------------------------------------------
# Task 11 — ping gets pong
# ---------------------------------------------------------------------------


async def test_ping_gets_pong(client: AsyncTestClient) -> None:
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# ---------------------------------------------------------------------------
# Task 12 — registry subscribe/unsubscribe seam
# ---------------------------------------------------------------------------


class _SpyRegistry:
    def __init__(self) -> None:
        self.subscribed: list[uuid.UUID] = []
        self.unsubscribed: list[uuid.UUID] = []

    async def subscribe(self, tenant_id: uuid.UUID, socket: object) -> None:
        self.subscribed.append(tenant_id)

    async def unsubscribe(self, tenant_id: uuid.UUID, socket: object) -> None:
        self.unsubscribed.append(tenant_id)

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        return


async def test_registry_subscribe_unsubscribe_called(
    client: AsyncTestClient, app: Litestar
) -> None:
    spy = _SpyRegistry()
    app.state.subscriber_registry = spy
    with (await client.websocket_connect("/sync/live")) as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"
    # The WebSocket ASGI task runs on the shared portal's background thread,
    # not the test's event loop, so asyncio.sleep(0) is not enough to wait
    # for the server's finally block to run unsubscribe.  A short real-time
    # sleep gives the portal thread time to drain.
    await asyncio.sleep(0.05)
    assert spy.subscribed == [DEV_TENANT_ID]
    assert spy.unsubscribed == [DEV_TENANT_ID]
