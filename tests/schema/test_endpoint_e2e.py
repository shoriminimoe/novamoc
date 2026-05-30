from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.data import Asset, AssetFieldValue
from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from litestar import Litestar


@pytest.fixture
def fresh_entity_id() -> str:
    return str(uuid4())


def _app_engine(app: Litestar) -> AsyncEngine:
    # Same lookup the events e2e suite uses — advanced_alchemy stores
    # the engine under a per-app numeric-suffixed key.
    for key, value in app.state._state.items():
        if key.startswith("db_engine") and isinstance(value, AsyncEngine):
            return value
    msg = "no SQLAlchemy engine on app state — did lifespan run?"
    raise RuntimeError(msg)


async def _query(app: Litestar, stmt: Any) -> Any:
    engine = _app_engine(app)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        return await session.execute(stmt)


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


async def test_post_schema_without_session_returns_401(unauth_client) -> None:
    """Middleware rejects requests with no session cookie before the route runs."""
    resp = await unauth_client.post(
        "/schema",
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


async def test_clear_asset_type_field_wipes_projection(client, app: Litestar) -> None:
    """``clear_asset_type_field`` deletes field-value rows and nulls the
    matching key in ``properties`` (issue #7, ADR-008, ADR-019)."""
    type_id = uuid4()
    field_id = uuid4()
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(type_id),
            "payload": {"name": f"Truck-{type_id}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": str(field_id),
            "payload": {
                "parent_id": str(type_id),
                "name": "vin",
                "data_type": "text",
            },
        },
    )
    assert resp.status_code in (200, 201), resp.text

    # Seed an asset + a vin value directly into the projection so we have
    # something to wipe. The data projection is normally produced by the
    # events fold; for this targeted test we write the rows directly.
    asset_id = uuid4()
    engine = _app_engine(app)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    with use_tenant(DEV_TENANT_ID):
        async with session_maker() as db:
            db.add(
                Asset(
                    id=asset_id,
                    tenant_id=DEV_TENANT_ID,
                    type_id=type_id,
                    name=None,
                    properties={str(field_id): "ABC123", "keep": "untouched"},
                    deleted=False,
                    row_state_hlc="0001700000000000-00000-aaa",
                )
            )
            db.add(
                AssetFieldValue(
                    tenant_id=DEV_TENANT_ID,
                    asset_id=asset_id,
                    field_id=str(field_id),
                    value_json="ABC123",
                    hlc="0001700000000000-00000-aaa",
                )
            )
            await db.commit()

    resp = await client.post(
        "/schema",
        json={
            "type": "clear_asset_type_field",
            "entity_id": str(field_id),
            "payload": {},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["outcome"] == "cleared"

    with use_tenant(DEV_TENANT_ID):
        rows = (
            (
                await _query(
                    app,
                    select(AssetFieldValue).where(
                        AssetFieldValue.field_id == str(field_id)
                    ),
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

        asset = (
            await _query(app, select(Asset).where(Asset.id == asset_id))
        ).scalar_one()
        # ADR-019: key stays as JSON null, sibling keys untouched.
        assert str(field_id) in asset.properties
        assert asset.properties[str(field_id)] is None
        assert asset.properties["keep"] == "untouched"


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
