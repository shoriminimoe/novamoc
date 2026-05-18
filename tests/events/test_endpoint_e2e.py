"""End-to-end tests for ``POST /events`` over ``AsyncTestClient`` (M1.9).

These tests verify the full apply pipeline — event_log append +
field-value fold + entity-table projection + row-state — against a
real SQLite engine. The engine is the one Litestar's SQLAlchemy
plugin installed on the app, so reads after a POST observe the
projection the request just wrote (one transaction per request,
committed by the autocommit before_send handler).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    EventLog,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from uuid import UUID

    from litestar import Litestar
    from litestar.testing import AsyncTestClient


_VALID_HLC = "0000000000000001-00000-client-a"
_LATER_HLC = "0000000000000002-00000-client-a"


def _app_engine(app: Litestar) -> AsyncEngine:
    # advanced_alchemy stores the engine under ``db_engine`` plus a
    # per-instance numeric suffix (it ``_ensure_unique``-s the key
    # against a class-level registry so multiple apps within one
    # process do not collide). The plugin only installs one engine
    # per app, so pick whichever key starts with the base name.
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


async def _make_asset_field(
    client: AsyncTestClient, *, data_type: str = "text"
) -> tuple[UUID, UUID, int]:
    """Create an asset_type + field via POST /schema. Returns
    (type_id, field_id, schema_version)."""
    type_id = uuid4()
    field_id = uuid4()
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(type_id),
            "payload": {"name": f"Truck-{uuid4()}"},
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
                "data_type": data_type,
            },
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, field_id, int(resp.json()["schema_version"])


def _created_event(
    *,
    type_id: UUID,
    instance_id: UUID,
    hlc: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    return {
        "hlc": hlc,
        "family": "asset",
        "type_id": str(type_id),
        "instance_id": str(instance_id),
        "body": {"event": "created", "values": values},
    }


def _mr_created_event(
    *,
    type_id: UUID,
    instance_id: UUID,
    hlc: str,
    values: dict[str, Any],
    parent: dict[str, str] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"event": "created", "values": values}
    if parent is not None:
        body["parent"] = parent
    return {
        "hlc": hlc,
        "family": "maintenance_record",
        "type_id": str(type_id),
        "instance_id": str(instance_id),
        "body": body,
    }


async def _make_mr_field(
    client: AsyncTestClient, *, data_type: str = "text"
) -> tuple[UUID, UUID, int]:
    """Create a maintenance_record_type + field via POST /schema. Returns
    (type_id, field_id, schema_version)."""
    type_id = uuid4()
    field_id = uuid4()
    resp = await client.post(
        "/schema",
        json={
            "type": "create_maintenance_record_type",
            "entity_id": str(type_id),
            "payload": {"name": f"OilChange-{uuid4()}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    resp = await client.post(
        "/schema",
        json={
            "type": "create_maintenance_record_type_field",
            "entity_id": str(field_id),
            "payload": {
                "parent_id": str(type_id),
                "name": "mileage",
                "data_type": data_type,
            },
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, field_id, int(resp.json()["schema_version"])


async def _create_parent_asset(
    client: AsyncTestClient, *, hlc: str
) -> tuple[UUID, UUID, int]:
    """Seed an asset_type + asset instance so an MR can reference it.

    Returns ``(asset_type_id, asset_instance_id, schema_version)``. The
    asset_type is created via ``POST /schema`` (bumping the tenant's
    schema_version) and the asset row via ``POST /events`` (each
    request commits its own transaction so the FK is satisfied by the
    time the MR event lands). The returned ``schema_version`` is the
    post-create value — callers reuse it for subsequent events so the
    schema-version gate stays in sync.
    """
    asset_type_id = uuid4()
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(asset_type_id),
            "payload": {"name": f"Truck-{uuid4()}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    schema_version = int(resp.json()["schema_version"])

    asset_instance_id = uuid4()
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                _created_event(
                    type_id=asset_type_id,
                    instance_id=asset_instance_id,
                    hlc=hlc,
                    values={"col:name": "Parent-Truck"},
                )
            ],
        },
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted", resp.text
    return asset_type_id, asset_instance_id, schema_version


async def test_happy_path_writes_log_field_values_and_entity_row(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, field_id, schema_version = await _make_asset_field(client)
    instance_id = uuid4()
    event = _created_event(
        type_id=type_id,
        instance_id=instance_id,
        hlc=_VALID_HLC,
        values={"col:name": "Truck-1", str(field_id): "ABC123"},
    )

    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        # event_log row exists.
        count = (
            await _query(app, select(func.count()).select_from(EventLog))
        ).scalar_one()
        assert count == 1

        # asset_field_values has both cells.
        rows = (
            await _query(
                app,
                select(AssetFieldValue.field_id, AssetFieldValue.value_json).where(
                    AssetFieldValue.asset_id == instance_id
                ),
            )
        ).all()
        by_field = {row.field_id: row.value_json for row in rows}
        assert by_field == {"col:name": "Truck-1", str(field_id): "ABC123"}

        # Entity row materialized with col:name on the column and the
        # user field in properties.
        asset = (
            await _query(app, select(Asset).where(Asset.id == instance_id))
        ).scalar_one()
        assert asset.name == "Truck-1"
        assert asset.deleted is False
        assert asset.properties == {str(field_id): "ABC123"}


async def test_replay_returns_all_duplicate_and_preserves_state(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, field_id, schema_version = await _make_asset_field(client)
    instance_id = uuid4()
    body = {
        "schema_version": schema_version,
        "events": [
            _created_event(
                type_id=type_id,
                instance_id=instance_id,
                hlc=_VALID_HLC,
                values={str(field_id): "ABC123"},
            )
        ],
    }

    first = await client.post("/events", json=body)
    assert first.status_code == 202
    second = await client.post("/events", json=body)
    assert second.status_code == 202
    assert second.json()["outcomes"][0]["outcome"] == "duplicate"

    with use_tenant(DEV_TENANT_ID):
        count = (
            await _query(app, select(func.count()).select_from(EventLog))
        ).scalar_one()
        # One row, not two — the duplicate didn't append.
        assert count == 1


async def test_lww_concurrent_events_higher_hlc_wins(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, field_id, schema_version = await _make_asset_field(client)
    instance_id = uuid4()

    # Post the LATER HLC first, then the EARLIER one — the later
    # value must still win because the strict-greater HLC guard
    # in M1.6's fold rejects the second event's overwrite attempt.
    later_event = _created_event(
        type_id=type_id,
        instance_id=instance_id,
        hlc=_LATER_HLC,
        values={str(field_id): "LATER-WINS"},
    )
    earlier_event = _created_event(
        type_id=type_id,
        instance_id=instance_id,
        hlc=_VALID_HLC,
        values={str(field_id): "EARLIER-LOSES"},
    )

    resp = await client.post(
        "/events",
        json={"schema_version": schema_version, "events": [later_event]},
    )
    assert resp.status_code == 202
    resp = await client.post(
        "/events",
        json={"schema_version": schema_version, "events": [earlier_event]},
    )
    assert resp.status_code == 202
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        asset = (
            await _query(app, select(Asset).where(Asset.id == instance_id))
        ).scalar_one()
        assert asset.properties == {str(field_id): "LATER-WINS"}
        row = (
            await _query(
                app,
                select(AssetFieldValue.hlc, AssetFieldValue.value_json).where(
                    AssetFieldValue.asset_id == instance_id,
                    AssetFieldValue.field_id == str(field_id),
                ),
            )
        ).first()
        assert row.hlc == _LATER_HLC
        assert row.value_json == "LATER-WINS"


async def test_hlc_drift_rejected_per_event(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _make_asset_field(client)
    future_hlc = "9999999999999999-00000-client-a"
    event = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc=future_hlc,
        values={"col:name": "x"},
    )
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.status_code == 202
    assert resp.json()["outcomes"][0]["outcome"] == "rejected:hlc_drift_exceeded"


async def test_stale_schema_version_returns_409(client: AsyncTestClient) -> None:
    await _make_asset_field(client)  # bump schema_version to >0
    event = _created_event(
        type_id=uuid4(), instance_id=uuid4(), hlc=_VALID_HLC, values={}
    )
    resp = await client.post("/events", json={"schema_version": 0, "events": [event]})
    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "http://test/problems/schema_version_stale.html"


async def test_unknown_field_per_event_outcome(client: AsyncTestClient) -> None:
    type_id, _field_id, schema_version = await _make_asset_field(client)
    bogus = uuid4()
    event = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc=_VALID_HLC,
        values={str(bogus): "x"},
    )
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.json()["outcomes"][0]["outcome"] == "rejected:unknown_field"


async def test_value_type_mismatch_per_event_outcome(client: AsyncTestClient) -> None:
    type_id, field_id, schema_version = await _make_asset_field(
        client, data_type="integer"
    )
    event = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc=_VALID_HLC,
        values={str(field_id): "not-a-number"},
    )
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.json()["outcomes"][0]["outcome"] == "rejected:value_type_mismatch"


async def test_tombstoned_field_event_is_accepted(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, field_id, _schema_after_create = await _make_asset_field(client)
    resp = await client.post(
        "/schema",
        json={"type": "deactivate_asset_type_field", "entity_id": str(field_id)},
    )
    assert resp.status_code in (200, 201)
    schema_version = int(resp.json()["schema_version"])

    instance_id = uuid4()
    event = _created_event(
        type_id=type_id,
        instance_id=instance_id,
        hlc=_VALID_HLC,
        values={str(field_id): "still-recorded"},
    )
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        asset = (
            await _query(app, select(Asset).where(Asset.id == instance_id))
        ).scalar_one()
        assert asset.properties == {str(field_id): "still-recorded"}


async def test_delete_then_post_delete_edit_then_restore(
    client: AsyncTestClient, app: Litestar
) -> None:
    # Lifecycle from ADR-012: a post-delete field edit must land in
    # *_field_values + properties (data fold decoupled from row
    # visibility), and a later restore must surface it.
    type_id, field_id, schema_version = await _make_asset_field(client)
    instance_id = uuid4()

    hlc_create = "0000000000000001-00000-client-a"
    hlc_delete = "0000000000000002-00000-client-a"
    hlc_edit = "0000000000000003-00000-client-a"
    hlc_restore = "0000000000000004-00000-client-a"

    # Create
    create_event = _created_event(
        type_id=type_id,
        instance_id=instance_id,
        hlc=hlc_create,
        values={str(field_id): "BEFORE-DELETE"},
    )
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [create_event]}
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    # Deactivate the entity
    deactivate_event = {
        "hlc": hlc_delete,
        "family": "asset",
        "type_id": str(type_id),
        "instance_id": str(instance_id),
        "body": {"event": "deactivated"},
    }
    resp = await client.post(
        "/events",
        json={"schema_version": schema_version, "events": [deactivate_event]},
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    # Field edit while tombstoned (Updated event)
    edit_event = {
        "hlc": hlc_edit,
        "family": "asset",
        "type_id": str(type_id),
        "instance_id": str(instance_id),
        "body": {"event": "updated", "values": {str(field_id): "POST-DELETE-EDIT"}},
    }
    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [edit_event]}
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    # Now activate the entity (restoration).
    restore_event = {
        "hlc": hlc_restore,
        "family": "asset",
        "type_id": str(type_id),
        "instance_id": str(instance_id),
        "body": {"event": "activated"},
    }
    resp = await client.post(
        "/events",
        json={"schema_version": schema_version, "events": [restore_event]},
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        asset = (
            await _query(app, select(Asset).where(Asset.id == instance_id))
        ).scalar_one()
        assert asset.deleted is False
        assert asset.row_state_hlc == hlc_restore
        # The post-delete edit surfaces in the restored projection.
        assert asset.properties == {str(field_id): "POST-DELETE-EDIT"}


async def test_mixed_outcome_batch_appends_only_accepted_events(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, _field_id, schema_version = await _make_asset_field(client)
    good_event_1 = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc="0000000000000001-00000-client-a",
        values={"col:name": "Good-1"},
    )
    bad_event = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc="0000000000000002-00000-client-a",
        # col:bogus is unknown → rejected
        values={"col:bogus": "x"},
    )
    good_event_2 = _created_event(
        type_id=type_id,
        instance_id=uuid4(),
        hlc="0000000000000003-00000-client-a",
        values={"col:name": "Good-2"},
    )

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [good_event_1, bad_event, good_event_2],
        },
    )
    assert resp.status_code == 202
    outcomes = resp.json()["outcomes"]
    assert [o["outcome"] for o in outcomes] == [
        "accepted",
        "rejected:unknown_field",
        "accepted",
    ]

    with use_tenant(DEV_TENANT_ID):
        # event_log gained 2 rows, not 3 — the rejected event did not
        # append.
        count = (
            await _query(app, select(func.count()).select_from(EventLog))
        ).scalar_one()
        assert count == 2


# --- maintenance_record-family coverage ---
#
# The events endpoint dispatches by ``(family, body type)`` to two
# distinct handler modules (``_handlers/asset.py`` vs
# ``_handlers/maintenance_record.py``); asset coverage above does not
# transitively cover MR. These tests exercise the same full pipeline
# (event_log + field-value fold + entity-table projection + row-state)
# for the MR family, including the ``parent`` reference Created carries
# and the ADR-012 row lifecycle.


async def test_mr_happy_path_writes_log_field_values_and_entity_row(
    client: AsyncTestClient, app: Litestar
) -> None:
    # Order matters: create the parent asset_type+instance first so the
    # MR type creation returns the post-everything schema_version.
    parent_type_id, parent_asset_id, _ = await _create_parent_asset(
        client, hlc=_VALID_HLC
    )
    mr_type_id, mr_field_id, schema_version = await _make_mr_field(client)
    mr_instance_id = uuid4()
    event = _mr_created_event(
        type_id=mr_type_id,
        instance_id=mr_instance_id,
        hlc=_LATER_HLC,
        values={"col:name": "Oil-Change-#1", str(mr_field_id): "120000"},
        parent={"type_id": str(parent_type_id), "instance_id": str(parent_asset_id)},
    )

    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        # event_log gained one row (the parent asset Create added one
        # earlier — two total).
        count = (
            await _query(app, select(func.count()).select_from(EventLog))
        ).scalar_one()
        assert count == 2

        # maintenance_record_field_values has both cells under the MR id.
        rows = (
            await _query(
                app,
                select(
                    MaintenanceRecordFieldValue.field_id,
                    MaintenanceRecordFieldValue.value_json,
                ).where(
                    MaintenanceRecordFieldValue.maintenance_record_id == mr_instance_id
                ),
            )
        ).all()
        by_field = {row.field_id: row.value_json for row in rows}
        assert by_field == {"col:name": "Oil-Change-#1", str(mr_field_id): "120000"}

        # Entity row materialized with the parent FK on asset_id, name
        # on the column, and the user field in properties.
        mr = (
            await _query(
                app,
                select(MaintenanceRecord).where(MaintenanceRecord.id == mr_instance_id),
            )
        ).scalar_one()
        assert mr.name == "Oil-Change-#1"
        assert mr.asset_id == parent_asset_id
        assert mr.deleted is False
        assert mr.properties == {str(mr_field_id): "120000"}


async def test_mr_created_without_parent_rejected_not_500(
    client: AsyncTestClient, app: Litestar
) -> None:
    # Regression for 907c8ce: an MR Created event with no ``parent``
    # used to raise a bare ValueError that the controller's per-event
    # catch did not handle, turning the whole batch into a 500. It must
    # surface as a per-event ``rejected:invalid_payload_shape`` in a
    # normal 202 envelope, and the event_log must not gain a row.
    mr_type_id, _mr_field_id, schema_version = await _make_mr_field(client)
    event = _mr_created_event(
        type_id=mr_type_id,
        instance_id=uuid4(),
        hlc=_VALID_HLC,
        values={"col:name": "Orphan-MR"},
        parent=None,
    )

    resp = await client.post(
        "/events", json={"schema_version": schema_version, "events": [event]}
    )
    assert resp.status_code == 202, resp.text
    outcome = resp.json()["outcomes"][0]
    assert outcome["outcome"] == "rejected:invalid_payload_shape"
    assert "invalid_payload_shape" in outcome["problem"]["type"]

    with use_tenant(DEV_TENANT_ID):
        count = (
            await _query(app, select(func.count()).select_from(EventLog))
        ).scalar_one()
        assert count == 0


async def test_mr_delete_then_post_delete_edit_then_restore(
    client: AsyncTestClient, app: Litestar
) -> None:
    # ADR-012 lifecycle on the MR family: deactivate the MR, edit a
    # field while tombstoned (the cell-value fold runs regardless of
    # row visibility), then restore the MR and assert the post-delete
    # value is what surfaces in the entity row.
    parent_type_id, parent_asset_id, _ = await _create_parent_asset(
        client, hlc="0000000000000000-00000-client-a"
    )
    mr_type_id, mr_field_id, schema_version = await _make_mr_field(client)
    mr_instance_id = uuid4()

    hlc_create = "0000000000000001-00000-client-a"
    hlc_delete = "0000000000000002-00000-client-a"
    hlc_edit = "0000000000000003-00000-client-a"
    hlc_restore = "0000000000000004-00000-client-a"

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                _mr_created_event(
                    type_id=mr_type_id,
                    instance_id=mr_instance_id,
                    hlc=hlc_create,
                    values={str(mr_field_id): "BEFORE-DELETE"},
                    parent={
                        "type_id": str(parent_type_id),
                        "instance_id": str(parent_asset_id),
                    },
                )
            ],
        },
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted", resp.text

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": hlc_delete,
                    "family": "maintenance_record",
                    "type_id": str(mr_type_id),
                    "instance_id": str(mr_instance_id),
                    "body": {"event": "deactivated"},
                }
            ],
        },
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": hlc_edit,
                    "family": "maintenance_record",
                    "type_id": str(mr_type_id),
                    "instance_id": str(mr_instance_id),
                    "body": {
                        "event": "updated",
                        "values": {str(mr_field_id): "POST-DELETE-EDIT"},
                    },
                }
            ],
        },
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": hlc_restore,
                    "family": "maintenance_record",
                    "type_id": str(mr_type_id),
                    "instance_id": str(mr_instance_id),
                    "body": {"event": "activated"},
                }
            ],
        },
    )
    assert resp.json()["outcomes"][0]["outcome"] == "accepted"

    with use_tenant(DEV_TENANT_ID):
        mr = (
            await _query(
                app,
                select(MaintenanceRecord).where(MaintenanceRecord.id == mr_instance_id),
            )
        ).scalar_one()
        assert mr.deleted is False
        assert mr.row_state_hlc == hlc_restore
        assert mr.properties == {str(mr_field_id): "POST-DELETE-EDIT"}
