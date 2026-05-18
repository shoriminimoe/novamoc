"""``GET /events`` catch-up endpoint (M2.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_get_events_empty_stream_returns_no_items(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["cursor"] is None
    assert body["results_per_page"] == 500


async def test_get_events_returns_appended_events(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())
    post = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000000-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {
                        "event": "created",
                        "values": {"col:name": "Truck-1"},
                    },
                }
            ],
        },
    )
    assert post.status_code == 202, post.text

    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    event = body["items"][0]
    assert event["hlc"] == "0001700000000000-00000-abc"
    assert event["family"] == "asset"
    assert event["type_id"] == type_id
    assert event["instance_id"] == instance_id
    assert event["body"] == {
        "event": "created",
        "parent": None,
        "values": {"col:name": "Truck-1"},
    }
    assert event["seq"] > 0
    assert event["schema_version"] == 0
    assert "received_at" in event
    assert body["cursor"] is None
