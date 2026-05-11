"""Scaffold-level tests for ``POST /events`` (M1.1)."""

from __future__ import annotations

from uuid import uuid4


async def test_post_events_returns_202_for_valid_batch(client) -> None:
    resp = await client.post(
        "/events",
        json={
            "schema_version": 1,
            "events": [
                {
                    "hlc": "0001700000000000-00000-abc",
                    "family": "asset",
                    "type_id": str(uuid4()),
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


async def test_post_events_accepts_empty_batch(client) -> None:
    # Empty batches are syntactically valid; this issue is scaffold-only
    # and explicitly defers all validation to later milestones (M1.2+).
    resp = await client.post(
        "/events",
        json={"schema_version": 1, "events": []},
    )
    assert resp.status_code == 202, resp.text
