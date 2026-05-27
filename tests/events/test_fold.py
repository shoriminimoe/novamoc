"""Unit tests for the field-value LWW fold (M1.6, ADR-007 / ADR-012)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from novamoc.db.models.data import AssetFieldValue, MaintenanceRecordFieldValue
from novamoc.domain.events._fold import FieldUpsert, apply_field_value
from novamoc.domain.events._payloads import EntityFamily
from tests.data.seed_helpers import seed_asset, seed_maintenance_record

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_HLC_EARLIER = "0000000000000001-00000-client-a"
_HLC_LATER = "0000000000000002-00000-client-a"


async def _stored_row(
    session: AsyncSession,
    *,
    asset_id: UUID,
    field_id: str,
) -> tuple[str, object] | None:
    stmt = select(AssetFieldValue.hlc, AssetFieldValue.value_json).where(
        AssetFieldValue.asset_id == asset_id,
        AssetFieldValue.field_id == field_id,
    )
    result = await session.execute(stmt)
    row = result.first()
    return None if row is None else (row.hlc, row.value_json)


def _asset_upsert(
    *, asset_id: UUID, field_id: str = "col:name", value: object, hlc: str
) -> FieldUpsert:
    return FieldUpsert(
        family=EntityFamily.ASSET,
        instance_id=asset_id,
        field_id=field_id,
        value=value,
        hlc=hlc,
    )


async def test_forward_order_stores_latest_value(session: AsyncSession) -> None:
    asset_id = await seed_asset(session)
    assert (
        await apply_field_value(
            session,
            _asset_upsert(asset_id=asset_id, value="Truck-1", hlc=_HLC_EARLIER),
        )
        is True
    )
    assert (
        await apply_field_value(
            session,
            _asset_upsert(asset_id=asset_id, value="Truck-2", hlc=_HLC_LATER),
        )
        is True
    )
    assert await _stored_row(session, asset_id=asset_id, field_id="col:name") == (
        _HLC_LATER,
        "Truck-2",
    )


async def test_reverse_order_keeps_higher_hlc(session: AsyncSession) -> None:
    asset_id = await seed_asset(session)
    await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value="Truck-LATE", hlc=_HLC_LATER),
    )
    applied = await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value="Truck-EARLY", hlc=_HLC_EARLIER),
    )
    assert applied is False
    assert await _stored_row(session, asset_id=asset_id, field_id="col:name") == (
        _HLC_LATER,
        "Truck-LATE",
    )


async def test_equal_hlc_does_not_apply(session: AsyncSession) -> None:
    # ADR-007 LWW is strict-greater; an event tied on HLC should NOT
    # overwrite, otherwise re-delivery would be non-idempotent at the
    # projection level even when it's idempotent at the log level.
    asset_id = await seed_asset(session)
    await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value="ORIGINAL", hlc=_HLC_EARLIER),
    )
    applied = await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value="REPLAY", hlc=_HLC_EARLIER),
    )
    assert applied is False
    assert await _stored_row(session, asset_id=asset_id, field_id="col:name") == (
        _HLC_EARLIER,
        "ORIGINAL",
    )


async def test_null_value_is_recorded(session: AsyncSession) -> None:
    asset_id = await seed_asset(session)
    await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value="something", hlc=_HLC_EARLIER),
    )
    applied = await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, value=None, hlc=_HLC_LATER),
    )
    assert applied is True
    assert await _stored_row(session, asset_id=asset_id, field_id="col:name") == (
        _HLC_LATER,
        None,
    )


async def test_maintenance_record_family_routes_to_correct_table(
    session: AsyncSession,
) -> None:
    record_id = await seed_maintenance_record(session)
    applied = await apply_field_value(
        session,
        FieldUpsert(
            family=EntityFamily.MAINTENANCE_RECORD,
            instance_id=record_id,
            field_id="col:name",
            value="oil-change",
            hlc=_HLC_EARLIER,
        ),
    )
    assert applied is True

    asset_hit = await session.execute(
        select(AssetFieldValue).where(AssetFieldValue.asset_id == record_id)
    )
    assert asset_hit.first() is None

    mr_hit = await session.execute(
        select(MaintenanceRecordFieldValue).where(
            MaintenanceRecordFieldValue.maintenance_record_id == record_id
        )
    )
    row = mr_hit.scalar_one()
    assert row.hlc == _HLC_EARLIER
    assert row.value_json == "oil-change"


async def test_different_fields_on_same_entity_are_independent(
    session: AsyncSession,
) -> None:
    asset_id = await seed_asset(session)
    field_a = str(uuid4())
    field_b = str(uuid4())

    await apply_field_value(
        session,
        _asset_upsert(asset_id=asset_id, field_id=field_a, value="A1", hlc=_HLC_LATER),
    )
    applied_b = await apply_field_value(
        session,
        _asset_upsert(
            asset_id=asset_id, field_id=field_b, value="B1", hlc=_HLC_EARLIER
        ),
    )
    # Different field, so the lower HLC still applies (no row to lose to).
    assert applied_b is True

    assert await _stored_row(session, asset_id=asset_id, field_id=field_a) == (
        _HLC_LATER,
        "A1",
    )
    assert await _stored_row(session, asset_id=asset_id, field_id=field_b) == (
        _HLC_EARLIER,
        "B1",
    )
