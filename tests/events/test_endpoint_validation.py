"""End-to-end tests for per-event schema validation on POST /events (M1.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


_VALID_HLC = "0000000000000001-00000-client-a"


async def _seed_asset_type_with_field(
    client: AsyncTestClient,
    *,
    field_data_type: str = "text",
) -> tuple[str, str, int]:
    """Create one asset type + one field via POST /schema.

    Returns ``(type_id, field_id, schema_version)``.
    """
    type_id = str(uuid4())
    field_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_id,
            "payload": {"name": f"Truck-{type_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text

    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": field_id,
            "payload": {
                "parent_id": type_id,
                "name": "vin",
                "data_type": field_data_type,
            },
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version = int(resp.json()["schema_version"])
    return type_id, field_id, schema_version


def _event(
    *,
    type_id: str,
    values: dict[str, object],
    instance_id: str | None = None,
) -> dict[str, object]:
    return {
        "hlc": _VALID_HLC,
        "family": "asset",
        "type_id": type_id,
        "instance_id": instance_id or str(uuid4()),
        "body": {"event": "created", "values": values},
    }


async def test_known_user_field_with_correct_type_is_accepted(
    client: AsyncTestClient,
) -> None:
    type_id, field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={field_id: "ABC123"})],
        },
    )
    assert resp.status_code == 202, resp.text


async def test_unknown_user_field_returns_404_unknown_field(
    client: AsyncTestClient,
) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    bogus_field_id = str(uuid4())
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={bogus_field_id: "x"})],
        },
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/unknown_field.html"
    assert body["title"] == "Unknown field"
    assert body["field"] == bogus_field_id
    assert body["family"] == "asset"
    assert body["type_id"] == type_id


async def test_field_under_different_type_reported_as_unknown(
    client: AsyncTestClient,
) -> None:
    # Field exists, but the event addresses a *different* asset type.
    _type_id_a, field_id, schema_version_a = await _seed_asset_type_with_field(client)
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

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version_b,
            # type_id_b has no fields of its own; field_id belongs to type_id_a.
            "events": [_event(type_id=type_id_b, values={field_id: "x"})],
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["type"] == "http://test/problems/unknown_field.html"


async def test_deactivated_field_is_still_accepted(client: AsyncTestClient) -> None:
    # ADR-012 keeps the data fold decoupled from schema visibility:
    # events for a deactivated (but undeleted) field must still land.
    type_id, field_id, _schema_version_after_create = await _seed_asset_type_with_field(
        client
    )
    resp = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type_field",
            "entity_id": field_id,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version_after_deactivate = int(resp.json()["schema_version"])

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version_after_deactivate,
            "events": [_event(type_id=type_id, values={field_id: "still works"})],
        },
    )
    assert resp.status_code == 202, resp.text


async def test_value_type_mismatch_returns_400(client: AsyncTestClient) -> None:
    type_id, field_id, schema_version = await _seed_asset_type_with_field(
        client, field_data_type="integer"
    )
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={field_id: "not-a-number"})],
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/value_type_mismatch.html"
    assert body["field"] == field_id
    assert body["expected"] == "integer"
    assert body["received"] == "string"


async def test_null_value_is_always_accepted(client: AsyncTestClient) -> None:
    # null is the cell-clearing sentinel; valid against any data_type.
    type_id, field_id, schema_version = await _seed_asset_type_with_field(
        client, field_data_type="integer"
    )
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": _VALID_HLC,
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": str(uuid4()),
                    "body": {"event": "updated", "values": {field_id: None}},
                }
            ],
        },
    )
    assert resp.status_code == 202, resp.text


async def test_col_name_accepts_text(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={"col:name": "Truck-7"})],
        },
    )
    assert resp.status_code == 202, resp.text


async def test_col_name_rejects_wrong_type(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={"col:name": 42})],
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/value_type_mismatch.html"
    assert body["field"] == "col:name"
    assert body["expected"] == "text"
    assert body["received"] == "integer"


async def test_unknown_col_returns_unknown_field(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={"col:bogus": "x"})],
        },
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/unknown_field.html"
    assert body["field"] == "col:bogus"


async def test_reserved_col_is_invalid_payload_shape(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={"col:deleted": True})],
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_non_uuid_non_col_key_is_invalid_payload_shape(
    client: AsyncTestClient,
) -> None:
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [_event(type_id=type_id, values={"not-a-uuid": "x"})],
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_deactivated_or_activated_event_has_no_value_validation(
    client: AsyncTestClient,
) -> None:
    # Row-state events carry no body.values, so the per-field validator
    # is a no-op. Sanity-check that they still reach the 202 path even
    # against a schema that has been bumped.
    type_id, _field_id, schema_version = await _seed_asset_type_with_field(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": _VALID_HLC,
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": str(uuid4()),
                    "body": {"event": "deactivated"},
                }
            ],
        },
    )
    assert resp.status_code == 202, resp.text
