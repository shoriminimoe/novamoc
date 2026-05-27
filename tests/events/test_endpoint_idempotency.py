"""Idempotency tests for ``POST /events`` (M1.5, ADR-011).

A retried batch with the same HLCs returns ``duplicate`` outcomes
instead of double-applying. The ``UNIQUE(tenant_id, hlc)`` constraint
on ``event_log`` is the underlying contract; the savepoint per insert
in the controller is what lets one duplicate co-exist with accepted
events in the same batch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.events._http_helpers import create_asset_type

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


_HLC_A = "0000000000000001-00000-client-a"
_HLC_B = "0000000000000002-00000-client-a"


def _event(
    hlc: str, *, type_id: str, instance_id: str | None = None
) -> dict[str, object]:
    return {
        "hlc": hlc,
        "family": "asset",
        "type_id": type_id,
        "instance_id": instance_id or str(uuid4()),
        "body": {"event": "created", "values": {"col:name": "x"}},
    }


async def test_fresh_batch_returns_all_accepted(client: AsyncTestClient) -> None:
    type_id, schema_version = await create_asset_type(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                _event(_HLC_A, type_id=type_id),
                _event(_HLC_B, type_id=type_id),
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    outcomes = resp.json()["outcomes"]
    assert [o["outcome"] for o in outcomes] == ["accepted", "accepted"]


async def test_replay_same_batch_returns_all_duplicate(
    client: AsyncTestClient,
) -> None:
    type_id, schema_version = await create_asset_type(client)
    body = {
        "schema_version": schema_version,
        "events": [
            _event(_HLC_A, type_id=type_id),
            _event(_HLC_B, type_id=type_id),
        ],
    }
    first = await client.post("/events", json=body)
    assert first.status_code == 202, first.text
    second = await client.post("/events", json=body)
    assert second.status_code == 202, second.text
    outcomes = second.json()["outcomes"]
    assert [o["outcome"] for o in outcomes] == ["duplicate", "duplicate"]


async def test_partial_replay_returns_mixed_outcomes(client: AsyncTestClient) -> None:
    type_id, schema_version = await create_asset_type(client)
    # First batch: only HLC_A.
    first = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(_HLC_A, type_id=type_id)],
        },
    )
    assert first.status_code == 202, first.text
    # Second batch: HLC_A (duplicate) followed by HLC_B (fresh).
    second = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                _event(_HLC_A, type_id=type_id),
                _event(_HLC_B, type_id=type_id),
            ],
        },
    )
    assert second.status_code == 202, second.text
    outcomes = second.json()["outcomes"]
    assert [o["outcome"] for o in outcomes] == ["duplicate", "accepted"]


async def test_rejection_does_not_consume_an_hlc(client: AsyncTestClient) -> None:
    # A rejected event must not occupy the (tenant_id, hlc) slot —
    # later, a fixed version of the same wire-event should be able to
    # append successfully without colliding.
    type_id, schema_version = await create_asset_type(client)
    bad_value_event = {
        "hlc": _HLC_A,
        "family": "asset",
        "type_id": type_id,
        "instance_id": str(uuid4()),
        # "col:bogus" is unknown_field — rejected, not stored.
        "body": {"event": "created", "values": {"col:bogus": "x"}},
    }
    first = await client.post(
        "/events",
        json={"schema_version": schema_version, "events": [bad_value_event]},
    )
    assert first.status_code == 202, first.text
    assert first.json()["outcomes"][0]["outcome"] == "rejected:unknown_field"

    # The same HLC is now free for a valid event.
    second = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(_HLC_A, type_id=type_id)],
        },
    )
    assert second.status_code == 202, second.text
    assert second.json()["outcomes"][0]["outcome"] == "accepted"
