from uuid import uuid4

import pytest


@pytest.fixture
def fresh_entity_id() -> str:
    return str(uuid4())


async def test_post_schema_creates_asset_type(client, fresh_entity_id: str) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
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
    assert err["type"] == "http://test/problems/name_reserved.html"
    assert err["title"] == "Name reserved"


async def test_post_schema_returns_404_for_update_missing(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "update_asset_type",
            "entity_id": str(uuid4()),
            "payload": {"name": "X"},
        },
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["type"] == "http://test/problems/entity_not_found.html"


async def test_post_schema_returns_400_on_unknown_command(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "do_a_barrel_roll",
            "entity_id": str(uuid4()),
            "payload": {},
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_post_schema_returns_400_on_payload_with_unknown_field(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "entity_id": str(uuid4()),
            "payload": {"name": "x"},  # forbidden field on _Empty
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_rollback_on_4xx_does_not_append_change_log(client) -> None:
    """A failed command must roll back: schema_version still advances by 1 between successful commands."""
    eid = str(uuid4())
    name = f"Rollback-{eid[:8]}"
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
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
            "entity_id": eid,
            "payload": {},
        },
    )
    assert deact.status_code in (200, 201)
    assert deact.json()["schema_version"] == sv_after_create + 1


async def test_post_schema_without_authorization_returns_401(client) -> None:
    """Middleware rejects requests with no credential before the route runs."""
    # The default `client` fixture attaches Authorization; we explicitly clear it.
    resp = await client.post(
        "/schema",
        headers={"Authorization": ""},
        json={
            "type": "create_asset_type",
            "entity_id": "00000000-0000-0000-0000-000000000999",
            "payload": {"name": "irrelevant"},
        },
    )
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"
    assert body["title"] == "Tenant not resolved"


async def test_asset_type_full_lifecycle(client) -> None:
    """Walk one asset_type through every accepted verb.

    Asserts that the entity round-trips through the snapshot, that
    ``schema_version`` advances by exactly one on every accepted
    command (including the two no-ops — handlers append a change-log
    row for received-but-no-op commands), and that a post-delete
    update reports ``entity_not_found``.
    """
    entity_id = str(uuid4())
    initial_name = f"Lifecycle-{entity_id[:8]}"
    renamed = f"{initial_name}-renamed"

    async def _step(verb: str, payload: dict, outcome: str) -> int:
        resp = await client.post(
            "/schema",
            json={"type": verb, "entity_id": entity_id, "payload": payload},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        assert body["entity_id"] == entity_id
        assert body["outcome"] == outcome
        return body["schema_version"]

    async def _snapshot_entry() -> dict | None:
        snap = await client.get("/schema")
        assert snap.status_code == 200, snap.text
        for t in snap.json()["asset_types"]:
            if t["id"] == entity_id:
                return t
        return None

    v = await _step("create_asset_type", {"name": initial_name}, "created")
    entry = await _snapshot_entry()
    assert entry is not None
    assert entry["name"] == initial_name
    assert entry["active"] is True

    # activate (no-op — already active). Still bumps version: handlers
    # append a change-log row for received-but-no-op commands.
    assert await _step("activate_asset_type", {}, "noop") == v + 1

    assert await _step("update_asset_type", {"name": renamed}, "updated") == v + 2
    entry = await _snapshot_entry()
    assert entry is not None
    assert entry["name"] == renamed
    assert entry["active"] is True

    assert await _step("deactivate_asset_type", {}, "deactivated") == v + 3
    entry = await _snapshot_entry()
    assert entry is not None
    assert entry["active"] is False

    # deactivate again — no-op on already-tombstoned. Still bumps version.
    assert await _step("deactivate_asset_type", {}, "noop") == v + 4

    assert await _step("activate_asset_type", {}, "activated") == v + 5
    entry = await _snapshot_entry()
    assert entry is not None
    assert entry["active"] is True
    assert entry["name"] == renamed  # rename survives the tombstone cycle.

    assert await _step("delete_asset_type", {}, "deleted") == v + 6
    assert await _snapshot_entry() is None

    # Update on a deleted id surfaces entity_not_found.
    resp = await client.post(
        "/schema",
        json={
            "type": "update_asset_type",
            "entity_id": entity_id,
            "payload": {"name": "post-delete"},
        },
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == "http://test/problems/entity_not_found.html"


async def test_post_schema_problem_includes_instance_and_extras(client) -> None:
    """RFC 9457 §3.2 extension members are rendered as top-level keys, and
    each occurrence carries an opaque `instance` URI for log correlation."""

    name = f"WithExtras-{uuid4()}"
    body = {
        "type": "create_asset_type",
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
