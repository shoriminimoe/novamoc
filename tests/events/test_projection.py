"""Unit tests for the entity-table projection mirror (M1.7, ADR-005 / ADR-012).

These rely on the ``seed`` fixture's scenarios (which insert baseline
``assets`` / ``maintenance_records`` rows — a stand-in for the M1.8
row-state path) and then exercise :func:`apply_entity_projection` on
them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.domain.events._fold import FieldUpsert
from novamoc.domain.events._payloads import EntityFamily
from novamoc.domain.events._projection import apply_entity_projection
from tests.data.scenarios import ACTIVE_OIL_CHANGE_RECORD, ACTIVE_TRUCK_WITH_ASSET

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.data.scenarios import Scenario


_ANY_HLC = "0000000000000001-00000-client-a"


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


async def test_col_name_writes_named_column(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value="Truck-1")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.name == "Truck-1"


async def test_col_null_value_nullifies_column(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value="Truck-1")
    )

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id="col:name", value=None)
    )

    asset = await _read_asset(session, asset_id)
    assert asset.name is None


async def test_user_field_writes_into_properties_json(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]
    field_id = str(uuid4())

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="ABC123")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_id: "ABC123"}


async def test_user_field_null_keeps_key_with_json_null_in_properties(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    # ADR-019: a cleared user field stays in ``properties`` as JSON
    # null rather than being removed.
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]
    field_id = str(uuid4())
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
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]
    field_id = str(uuid4())
    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="OLD")
    )

    await apply_entity_projection(
        session, _upsert(asset_id=asset_id, field_id=field_id, value="NEW")
    )

    asset = await _read_asset(session, asset_id)
    assert asset.properties == {field_id: "NEW"}


async def test_two_user_fields_coexist_in_properties(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    asset_id = (await seed(ACTIVE_TRUCK_WITH_ASSET))["asset"]["Primary Truck"]
    field_a = str(uuid4())
    field_b = str(uuid4())

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
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_RECORD)
    asset_id = ids["asset"]["Primary Truck"]
    record_id = ids["maintenance_record"]["Primary Oil Change"]

    upsert = FieldUpsert(
        family=EntityFamily.MAINTENANCE_RECORD,
        instance_id=record_id,
        field_id="col:name",
        value="oil-change",
        hlc=_ANY_HLC,
    )
    await apply_entity_projection(session, upsert)

    # The maintenance-record edit must not bleed into the asset's name.
    asset = await _read_asset(session, asset_id)
    assert asset.name == "Primary Truck"  # the seeded value, unchanged

    mr_row = (
        await session.execute(
            select(MaintenanceRecord).where(MaintenanceRecord.id == record_id)
        )
    ).scalar_one()
    assert mr_row.name == "oil-change"
