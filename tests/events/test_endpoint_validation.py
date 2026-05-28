"""End-to-end tests for per-event schema validation on POST /events (M1.4 + M1.5).

Per-event validation failures (unknown_field, value_type_mismatch,
invalid_payload_shape) surface as ``rejected:<code>`` entries in the
outcome list; the HTTP envelope still returns 202 (M1.5 acceptance
criteria — one rejected event must not poison the batch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from tests.events._http_helpers import (
    DEFAULT_HLC,
    event_envelope,
    seed_asset_type_with_field,
)

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def _post_one(
    client: AsyncTestClient, schema_version: int, event: dict[str, object]
) -> dict[str, Any]:
    """Post a one-event batch; return the single outcome."""
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.status_code == 202, resp.text
    outcomes = resp.json()["outcomes"]
    assert len(outcomes) == 1
    return outcomes[0]


async def test_known_user_field_with_correct_type_is_accepted(
    client: AsyncTestClient,
) -> None:
    type_id, field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={field_id: "ABC123"}),
    )
    assert outcome["outcome"] == "accepted"


async def test_unknown_user_field_rejects_unknown_field(
    client: AsyncTestClient,
) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    bogus_field_id = str(uuid4())
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={bogus_field_id: "x"}),
    )
    assert outcome["outcome"] == "rejected:unknown_field"
    # The exception's extras must reach the wire — without them clients
    # cannot diagnose which field on which type was unrecognised.
    problem = outcome["problem"]
    assert problem["type"].endswith("/problems/unknown_field.html")
    assert problem["status"] == 404
    assert problem["family"] == "asset"
    assert problem["type_id"] == type_id
    assert problem["field"] == bogus_field_id


async def test_field_under_different_type_reported_as_unknown(
    client: AsyncTestClient,
) -> None:
    _type_id_a, field_id, schema_version_a = await seed_asset_type_with_field(client)
    type_id_b = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_id_b,
            "payload": {"name": f"Other-{type_id_b[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version_b = int(resp.json()["schema_version"])
    assert schema_version_b > schema_version_a

    outcome = await _post_one(
        client,
        schema_version_b,
        event_envelope(type_id=type_id_b, values={field_id: "x"}),
    )
    assert outcome["outcome"] == "rejected:unknown_field"


async def test_deactivated_field_is_still_accepted(client: AsyncTestClient) -> None:
    type_id, field_id, _ = await seed_asset_type_with_field(client)
    resp = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type_field",
            "entity_id": field_id,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version_after_deactivate = int(resp.json()["schema_version"])

    outcome = await _post_one(
        client,
        schema_version_after_deactivate,
        event_envelope(type_id=type_id, values={field_id: "still works"}),
    )
    assert outcome["outcome"] == "accepted"


async def test_value_type_mismatch_rejects_with_code(client: AsyncTestClient) -> None:
    type_id, field_id, schema_version = await seed_asset_type_with_field(
        client, field_data_type="integer"
    )
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={field_id: "not-a-number"}),
    )
    assert outcome["outcome"] == "rejected:value_type_mismatch"
    problem = outcome["problem"]
    assert problem["type"].endswith("/problems/value_type_mismatch.html")
    assert problem["status"] == 400
    assert problem["field"] == field_id
    assert problem["expected"] == "integer"
    assert problem["received"] == "string"


async def test_null_value_is_always_accepted(client: AsyncTestClient) -> None:
    type_id, field_id, schema_version = await seed_asset_type_with_field(
        client, field_data_type="integer"
    )
    # Updated has no row-state component, so the asset row must exist
    # for the field-value fold's FK into ``assets`` to resolve. Seed it
    # via a prior Created event at an earlier HLC.
    instance_id = str(uuid4())
    seed_resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": "0000000000000000-00000-client-a",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert seed_resp.status_code == 202, seed_resp.text

    outcome = await _post_one(
        client,
        schema_version,
        {
            "hlc": DEFAULT_HLC,
            "family": "asset",
            "type_id": type_id,
            "instance_id": instance_id,
            "body": {"event": "updated", "values": {field_id: None}},
        },
    )
    assert outcome["outcome"] == "accepted"


async def test_col_name_accepts_text(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={"col:name": "Truck-7"}),
    )
    assert outcome["outcome"] == "accepted"


async def test_col_name_rejects_wrong_type(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={"col:name": 42}),
    )
    assert outcome["outcome"] == "rejected:value_type_mismatch"


async def test_unknown_col_returns_unknown_field(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={"col:bogus": "x"}),
    )
    assert outcome["outcome"] == "rejected:unknown_field"


async def test_reserved_col_is_invalid_payload_shape(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={"col:deleted": True}),
    )
    assert outcome["outcome"] == "rejected:invalid_payload_shape"


async def test_non_uuid_non_col_key_is_invalid_payload_shape(
    client: AsyncTestClient,
) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        event_envelope(type_id=type_id, values={"not-a-uuid": "x"}),
    )
    assert outcome["outcome"] == "rejected:invalid_payload_shape"


async def test_deactivated_or_activated_event_has_no_value_validation(
    client: AsyncTestClient,
) -> None:
    type_id, _field_id, schema_version = await seed_asset_type_with_field(client)
    outcome = await _post_one(
        client,
        schema_version,
        {
            "hlc": DEFAULT_HLC,
            "family": "asset",
            "type_id": type_id,
            "instance_id": str(uuid4()),
            "body": {"event": "deactivated"},
        },
    )
    assert outcome["outcome"] == "accepted"


async def test_mr_created_without_parent_is_invalid_payload_shape(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_maintenance_record_type",
            "entity_id": type_id,
            "payload": {"name": f"OilChange-{type_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version = int(resp.json()["schema_version"])

    outcome = await _post_one(
        client,
        schema_version,
        {
            "hlc": DEFAULT_HLC,
            "family": "maintenance_record",
            "type_id": type_id,
            "instance_id": str(uuid4()),
            "body": {"event": "created", "values": {}},
        },
    )
    assert outcome["outcome"] == "rejected:invalid_payload_shape"
    assert "invalid_payload_shape" in outcome["problem"]["type"]
