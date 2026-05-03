from uuid import uuid4

import pytest


_T = "tenant-e2e"


@pytest.fixture
def fresh_entity_id() -> str:
    return str(uuid4())


async def test_post_schema_creates_asset_type(client, fresh_entity_id: str) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": fresh_entity_id,
            "payload": {"name": f"Truck-{fresh_entity_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["outcome"] == "created"
    assert body["entity_id"] == fresh_entity_id
    assert body["schema_version"] >= 1


async def test_post_schema_returns_409_on_duplicate_name(client) -> None:
    name = f"DuplicateMe-{uuid4()}"
    body = {
        "type": "create_asset_type",
        "tenant_id": _T,
        "entity_id": str(uuid4()),
        "payload": {"name": name},
    }
    first = await client.post("/schema", json=body)
    assert first.status_code in (200, 201), first.text
    body["entity_id"] = str(uuid4())
    second = await client.post("/schema", json=body)
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    err = second.json()
    assert err["status"] == 409
    assert err["type"] == "urn:novamoc:problems:name_reserved"
    assert err["title"] == "Name reserved"


async def test_post_schema_returns_404_for_update_missing(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "update_asset_type",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {"name": "X"},
        },
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["type"] == "urn:novamoc:problems:entity_not_found"


async def test_post_schema_returns_400_on_unknown_command(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "do_a_barrel_roll",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {},
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == "urn:novamoc:problems:invalid_payload_shape"


async def test_post_schema_returns_400_on_payload_with_unknown_field(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {"name": "x"},  # forbidden field on _Empty
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "urn:novamoc:problems:invalid_payload_shape"


async def test_rollback_on_4xx_does_not_append_change_log(client) -> None:
    """A failed command must roll back: schema_version still advances by 1 between successful commands."""
    eid = str(uuid4())
    name = f"Rollback-{eid[:8]}"
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {"name": name},
        },
    )
    assert resp.status_code in (200, 201)
    sv_after_create = resp.json()["schema_version"]

    # Trigger a 409 (id collision on create) — must NOT append a change-log row.
    bad = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {"name": name},
        },
    )
    assert bad.status_code == 409

    # The next successful command's schema_version should be sv_after_create + 1.
    deact = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {},
        },
    )
    assert deact.status_code in (200, 201)
    assert deact.json()["schema_version"] == sv_after_create + 1


async def test_post_schema_problem_includes_instance_and_extras(client) -> None:
    """RFC 9457 §3.2 extension members are rendered as top-level keys, and
    each occurrence carries an opaque `instance` URI for log correlation."""

    name = f"WithExtras-{uuid4()}"
    body = {
        "type": "create_asset_type",
        "tenant_id": _T,
        "entity_id": str(uuid4()),
        "payload": {"name": name},
    }
    first = await client.post("/schema", json=body)
    assert first.status_code in (200, 201)
    body["entity_id"] = str(uuid4())
    second = await client.post("/schema", json=body)
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    err = second.json()
    # Extension member surfaced from `extras={"name": "..."}`.
    assert err["name"] == name
    # Per-occurrence instance.
    assert err["instance"].startswith("urn:uuid:")
