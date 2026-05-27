"""Unit tests for the entity-table projection mirror (M1.7, ADR-005 / ADR-012).

These insert an entity row directly into ``assets`` /
``maintenance_records`` (a stand-in for the M1.8 row-state path)
and then exercise :func:`apply_entity_projection` on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import insert, select

from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.domain.events._fold import FieldUpsert
from novamoc.domain.events._payloads import EntityFamily
from novamoc.domain.events._projection import apply_entity_projection
from tests._constants import DEV_TENANT_ID
from tests.data.seed_helpers import seed_asset_type, seed_mr_type

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_TENANT = DEV_TENANT_ID
_ANY_HLC = "0000000000000001-00000-client-a"


async def _seed_asset(session: AsyncSession, *, asset_id: UUID) -> None:
    """Stand-in for the M1.8 row-state path: insert a baseline asset row.

    Inserts the parent ``asset_types`` row first so the FK resolves
    under ``PRAGMA foreign_keys=ON``.
    """
    type_id = await seed_asset_type(session)
    await session.execute(
        insert(Asset).values(
            tenant_id=_TENANT,
            id=asset_id,
            type_id=type_id,
            name=None,
            properties={},
            deleted=False,
            row_state_hlc=_ANY_HLC,
        )
    )


async def _seed_maintenance_record(
    session: AsyncSession, *, record_id: UUID, asset_id: UUID
) -> None:
    type_id = await seed_mr_type(session)
    await session.execute(
        insert(MaintenanceRecord).values(
            tenant_id=_TENANT,
            id=record_id,
            type_id=type_id,
            asset_id=asset_id,
            name=None,
            properties={},
            deleted=False,
            row_state_hlc=_ANY_HLC,
        )
    )


async def _read_asset(session: AsyncSession, asset_id: UUID) -> Asset:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one()


def _upsert(
    *,
    asset_id: UUID,
    field_id: str,
    value: object,
) -> FieldUpsert:
    return FieldUpsert(
        family=EntityFamily.ASSET,
        instance_id=asset_id,
        field_id=field_id,
        value=value,
        hlc=_ANY_HLC,
    )


async def test_col_name_writes_named_column(session: AsyncSession) -> None:
    asset_id = uuid4()
    await _seed_asset(session, asset_id=asset_id)

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value="Truck-1")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.name == "Truck-1"


async def test_col_null_value_nullifies_column(session: AsyncSession) -> None:
    asset_id = uuid4()
    await _seed_asset(session, asset_id=asset_id)
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value="Truck-1")
    )

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value=None)
    )

    asset = await _read_asset(session, asset_id)
    assert asset.name is None


async def test_user_field_writes_into_properties_json(session: AsyncSession) -> None:
    asset_id = uuid4()
    field_id = str(uuid4())
    await _seed_asset(session, asset_id=asset_id)

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="ABC123")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_id: "ABC123"}


async def test_user_field_null_keeps_key_with_json_null_in_properties(
    session: AsyncSession,
) -> None:
    # ADR-019: a cleared user field stays in ``properties`` as JSON
    # null rather than being removed.
    asset_id = uuid4()
    field_id = str(uuid4())
    await _seed_asset(session, asset_id=asset_id)
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="VIN-123")
    )

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value=None)
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_id: None}


async def test_user_field_update_replaces_value_in_properties(
    session: AsyncSession,
) -> None:
    asset_id = uuid4()
    field_id = str(uuid4())
    await _seed_asset(session, asset_id=asset_id)
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="OLD")
    )

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="NEW")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_id: "NEW"}


async def test_two_user_fields_coexist_in_properties(session: AsyncSession) -> None:
    asset_id = uuid4()
    field_a = str(uuid4())
    field_b = str(uuid4())
    await _seed_asset(session, asset_id=asset_id)

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_a, value="A")
    )
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_b, value="B")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_a: "A", field_b: "B"}


async def test_missing_entity_row_is_a_noop(session: AsyncSession) -> None:
    # M1.7 must not crash when the entity row hasn't been created yet
    # (the M1.8 row-state path hasn't run). The UPDATE silently matches
    # zero rows; the M1.6 field-value row still exists and a later
    # M1.8 INSERT will materialize the entity row.
    missing_id = uuid4()
    await apply_entity_projection(
        session, _upsert(asset_id=missing_id, field_id="col:name", value="x")
    )

    result = await session.execute(select(Asset).where(Asset.id == missing_id))
    assert result.first() is None


async def test_maintenance_record_family_routes_to_correct_table(
    session: AsyncSession,
) -> None:
    asset_id = uuid4()
    record_id = uuid4()
    await _seed_asset(session, asset_id=asset_id)
    await _seed_maintenance_record(session, record_id=record_id, asset_id=asset_id)

    upsert = FieldUpsert(
        family=EntityFamily.MAINTENANCE_RECORD,
        instance_id=record_id,
        field_id="col:name",
        value="oil-change",
        hlc=_ANY_HLC,
    )
    await apply_entity_projection(session, upsert)

    asset = await _read_asset(session, asset_id)
    assert asset.name is None  # unrelated to the maintenance_record edit

    mr_row = (
        await session.execute(
            select(MaintenanceRecord).where(MaintenanceRecord.id == record_id)
        )
    ).scalar_one()
    assert mr_row.name == "oil-change"
