"""Unit tests for row-state apply (M1.8, ADR-012)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select

from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    EventEnvelope,
    Parent,
    Updated,
)
from novamoc.domain.events._row_state import apply_row_state

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_HLC_EARLIER = "0000000000000001-00000-client-a"
_HLC_MID = "0000000000000002-00000-client-a"
_HLC_LATER = "0000000000000003-00000-client-a"


def _create_event(*, instance_id: UUID, type_id: UUID, hlc: str) -> EventEnvelope:
    return EventEnvelope(
        hlc=hlc,
        family=EntityFamily.ASSET,
        type_id=type_id,
        instance_id=instance_id,
        body=Created(values={}),
    )


def _deactivate_event(*, instance_id: UUID, type_id: UUID, hlc: str) -> EventEnvelope:
    return EventEnvelope(
        hlc=hlc,
        family=EntityFamily.ASSET,
        type_id=type_id,
        instance_id=instance_id,
        body=Deactivated(),
    )


def _activate_event(*, instance_id: UUID, type_id: UUID, hlc: str) -> EventEnvelope:
    return EventEnvelope(
        hlc=hlc,
        family=EntityFamily.ASSET,
        type_id=type_id,
        instance_id=instance_id,
        body=Activated(),
    )


async def _read_asset(session: AsyncSession, asset_id: UUID) -> Asset | None:
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def test_created_inserts_entity_row(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    applied = await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_MID)
    )
    assert applied is True

    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.deleted is False
    assert asset.row_state_hlc == _HLC_MID
    assert asset.properties == {}
    assert asset.type_id == type_id


async def test_deactivate_sets_deleted_flag(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_EARLIER)
    )

    applied = await apply_row_state(
        session, _deactivate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_MID)
    )
    assert applied is True

    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.deleted is True
    assert asset.row_state_hlc == _HLC_MID


async def test_activate_restores_after_deactivate(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_EARLIER)
    )
    await apply_row_state(
        session, _deactivate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_MID)
    )

    applied = await apply_row_state(
        session, _activate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_LATER)
    )
    assert applied is True

    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.deleted is False
    assert asset.row_state_hlc == _HLC_LATER


async def test_stale_deactivate_is_noop(session: AsyncSession) -> None:
    # ADR-007's strict-greater rule: an event whose HLC is below the
    # current row_state_hlc must not flip the visibility bit.
    asset_id = uuid4()
    type_id = uuid4()
    await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_LATER)
    )

    applied = await apply_row_state(
        session,
        _deactivate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_EARLIER),
    )
    assert applied is False

    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.deleted is False
    assert asset.row_state_hlc == _HLC_LATER


async def test_activate_on_missing_row_is_noop(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    applied = await apply_row_state(
        session, _activate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_MID)
    )
    assert applied is False
    assert await _read_asset(session, asset_id) is None


async def test_deactivate_on_missing_row_is_noop(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    applied = await apply_row_state(
        session, _deactivate_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_MID)
    )
    assert applied is False
    assert await _read_asset(session, asset_id) is None


async def test_updated_is_noop_for_row_state(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_EARLIER)
    )
    applied = await apply_row_state(
        session,
        EventEnvelope(
            hlc=_HLC_LATER,
            family=EntityFamily.ASSET,
            type_id=type_id,
            instance_id=asset_id,
            body=Updated(values={"col:name": "x"}),
        ),
    )
    assert applied is False

    # row_state_hlc must NOT have advanced because Updated didn't touch
    # the row-state track.
    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.row_state_hlc == _HLC_EARLIER


async def test_replay_create_with_lower_hlc_is_noop(session: AsyncSession) -> None:
    asset_id = uuid4()
    type_id = uuid4()
    await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_LATER)
    )

    applied = await apply_row_state(
        session, _create_event(instance_id=asset_id, type_id=type_id, hlc=_HLC_EARLIER)
    )
    # The ON CONFLICT WHERE excluded.hlc > row_state_hlc filters this
    # out; RETURNING yields no row, so we report "not applied".
    assert applied is False

    asset = await _read_asset(session, asset_id)
    assert asset is not None
    assert asset.row_state_hlc == _HLC_LATER


async def test_created_maintenance_record_requires_parent(
    session: AsyncSession,
) -> None:
    record_id = uuid4()
    type_id = uuid4()
    event = EventEnvelope(
        hlc=_HLC_MID,
        family=EntityFamily.MAINTENANCE_RECORD,
        type_id=type_id,
        instance_id=record_id,
        body=Created(values={}),
    )
    with pytest.raises(PayloadShapeError, match="parent") as excinfo:
        await apply_row_state(session, event)
    assert excinfo.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


async def test_created_maintenance_record_with_parent_inserts(
    session: AsyncSession,
) -> None:
    asset_id = uuid4()
    asset_type_id = uuid4()
    # Seed the parent asset row first so the MR FK resolves.
    await apply_row_state(
        session,
        _create_event(instance_id=asset_id, type_id=asset_type_id, hlc=_HLC_EARLIER),
    )

    record_id = uuid4()
    record_type_id = uuid4()
    event = EventEnvelope(
        hlc=_HLC_MID,
        family=EntityFamily.MAINTENANCE_RECORD,
        type_id=record_type_id,
        instance_id=record_id,
        body=Created(
            parent=Parent(type_id=asset_type_id, instance_id=asset_id),
            values={},
        ),
    )
    applied = await apply_row_state(session, event)
    assert applied is True

    mr = (
        await session.execute(
            select(MaintenanceRecord).where(MaintenanceRecord.id == record_id)
        )
    ).scalar_one()
    assert mr.asset_id == asset_id
    assert mr.type_id == record_type_id
    assert mr.deleted is False
    assert mr.row_state_hlc == _HLC_MID
