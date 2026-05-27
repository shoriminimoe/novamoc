"""Smoke tests for ``POST /events`` (M1.1 scaffold + M1.5 outcomes)."""

from __future__ import annotations

from uuid import uuid4

from tests.events._http_helpers import create_asset_type


async def test_post_events_returns_202_with_accepted_outcome(client) -> None:
    type_id, schema_version = await create_asset_type(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": "0001700000000000-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": str(uuid4()),
                    "body": {
                        "event": "created",
                        "values": {"col:name": "Truck-1"},
                    },
                }
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body == {
        "outcomes": [
            {"hlc": "0001700000000000-00000-abc", "outcome": "accepted"},
        ]
    }


async def test_post_events_accepts_empty_batch(client) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": []},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"outcomes": []}
