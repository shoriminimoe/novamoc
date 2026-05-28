"""Schema-version gate tests for ``POST /events`` (M1.3, ADR-008/009).

A batch's ``schema_version`` must equal the tenant's current schema
version. The gate runs ahead of HLC parsing so a stale-schema client
gets the actionable error (re-fetch ``GET /schema``) rather than a
secondary HLC-format complaint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.events._http_helpers import event_envelope

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def _bump_schema_version(client: AsyncTestClient) -> tuple[str, int]:
    """Create one asset type via ``POST /schema``.

    Returns ``(type_id, server_schema_version)``.
    """
    type_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_id,
            "payload": {"name": f"Truck-{uuid4()}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, int(resp.json()["schema_version"])


async def test_fresh_tenant_accepts_version_zero(client: AsyncTestClient) -> None:
    # Fresh tenant: schema_version == 0 because no schema events have
    # been written. An empty events batch is sufficient signal for the
    # gate logic; a Created event would need a real ``type_id`` to
    # satisfy the FK from ``assets`` into ``asset_types`` and that
    # would force ``schema_version`` past 0.
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": []},
    )
    assert resp.status_code == 202, resp.text


async def test_stale_version_rejected_as_409(client: AsyncTestClient) -> None:
    _, version_after_create = await _bump_schema_version(client)
    assert version_after_create == 1

    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [event_envelope()]},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/schema_version_stale.html"
    assert body["title"] == "Schema version stale"
    assert body["status"] == 409
    assert body["expected"] == 1
    assert body["received"] == 0


async def test_future_version_also_rejected(client: AsyncTestClient) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 99, "events": [event_envelope()]},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/schema_version_stale.html"
    assert body["expected"] == 0
    assert body["received"] == 99


async def test_matched_version_after_schema_change_is_accepted(
    client: AsyncTestClient,
) -> None:
    type_id, version_after_create = await _bump_schema_version(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": version_after_create,
            "events": [event_envelope(type_id=type_id)],
        },
    )
    assert resp.status_code == 202, resp.text


async def test_version_gate_runs_before_hlc_validation(
    client: AsyncTestClient,
) -> None:
    # A stale-version batch should be rejected as schema_version_stale,
    # not invalid_payload_shape — even if its events have malformed HLCs.
    # The gate is the more actionable failure (re-fetch /schema) and the
    # client cannot proceed past it anyway.
    _ = await _bump_schema_version(client)
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [event_envelope(hlc="not-an-hlc")]},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["type"] == "http://test/problems/schema_version_stale.html"


async def test_empty_batch_with_mismatched_version_still_rejected(
    client: AsyncTestClient,
) -> None:
    _ = await _bump_schema_version(client)
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": []},
    )
    assert resp.status_code == 409, resp.text
