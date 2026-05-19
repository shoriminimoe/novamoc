"""Unit tests for ``InitialSyncPaginator``.

Run against an in-memory aiosqlite engine — no mocks, per the project's
testing rule. Each test builds its services inline against the
``session`` fixture from ``tests/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    EventLog,
    EventOp,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from novamoc.db.models.schema import (
    AssetType,
    MaintenanceRecordType,
    SchemaChangeLog,
)
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._pagination import InitialSyncPaginator
from novamoc.domain.sync._payloads import (
    AssetFieldValuesBatchBody,
    AssetsBatchBody,
    MaintenanceRecordFieldValuesBatchBody,
    MaintenanceRecordsBatchBody,
)
from novamoc.domain.sync.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def paginator(session: AsyncSession) -> InitialSyncPaginator:
    return InitialSyncPaginator(
        change_log_service=SchemaChangeLogService(session=session),
        event_log_service=EventLogService(session=session),
        asset_service=AssetService(session=session),
        asset_field_value_service=AssetFieldValueService(session=session),
        maintenance_record_service=MaintenanceRecordService(session=session),
        maintenance_record_field_value_service=(
            MaintenanceRecordFieldValueService(session=session)
        ),
    )


async def _make_asset_type(
    session: AsyncSession, *, name: str = "Truck", tenant_id: str = "t1"
) -> AssetType:
    asset_type = AssetType(id=uuid4(), tenant_id=tenant_id, name=name, active=True)
    session.add(asset_type)
    await session.flush()
    return asset_type


async def _make_maintenance_record_type(
    session: AsyncSession,
    *,
    name: str = "Inspection",
    tenant_id: str = "t1",
) -> MaintenanceRecordType:
    mrt = MaintenanceRecordType(id=uuid4(), tenant_id=tenant_id, name=name, active=True)
    session.add(mrt)
    await session.flush()
    return mrt


async def _make_asset(
    session: AsyncSession,
    *,
    type_id: UUID,
    tenant_id: str = "t1",
    deleted: bool = False,
    hlc: str = "0001700000000000-00000-abc",
) -> Asset:
    asset = Asset(
        id=uuid4(),
        tenant_id=tenant_id,
        type_id=type_id,
        name=None,
        properties={},
        deleted=deleted,
        row_state_hlc=hlc,
    )
    session.add(asset)
    await session.flush()
    return asset


async def _make_event(  # noqa: PLR0913  # test-helper builder: explicit keyword args > a dict literal
    session: AsyncSession,
    *,
    tenant_id: str = "t1",
    hlc: str,
    type_id: UUID,
    entity_id: UUID,
    schema_version: int = 0,
) -> None:
    session.add(
        EventLog(
            tenant_id=tenant_id,
            hlc=hlc,
            schema_version=schema_version,
            table_name="assets",
            type_id=str(type_id),
            entity_id=str(entity_id),
            field_id=None,
            op=EventOp.SET,
            value_json={"event": "created", "parent": None, "values": {}},
            received_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def _bump_schema_version(session: AsyncSession, *, tenant_id: str = "t1") -> int:
    """Append a no-op schema_change_log row to bump current_version()."""
    current = await session.execute(
        select(func.coalesce(func.max(SchemaChangeLog.seq), 0)).where(
            SchemaChangeLog.tenant_id == tenant_id
        )
    )
    next_seq = int(current.scalar_one()) + 1
    session.add(
        SchemaChangeLog(
            tenant_id=tenant_id,
            seq=next_seq,
            command=str(SchemaCommand.CREATE_ASSET_TYPE.value),
            entity_id=uuid4(),
            payload={"name": "Truck"},
        )
    )
    await session.flush()
    return next_seq


async def test_empty_tenant_returns_single_terminal_batch(
    paginator: InitialSyncPaginator,
) -> None:
    """Empty tenant collapses to one round-trip.

    Every intermediate table is skipped server-side; only the last
    table (which always emits, possibly empty) gets a batch — and
    that batch is terminal (``cursor=None``,
    ``event_log_cursor=start_seq``).
    """
    batch = await paginator(cursor=None, results_per_page=100)
    assert batch.schema_version == 0
    assert batch.cursor is None
    assert batch.event_log_cursor == 0
    assert isinstance(batch.body, MaintenanceRecordFieldValuesBatchBody)
    assert batch.body.items == ()


async def test_single_table_fits_one_page(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    for _ in range(3):
        await _make_asset(session, type_id=asset_type.id)

    batch = await paginator(cursor=None, results_per_page=100)
    assert isinstance(batch.body, AssetsBatchBody)
    assert len(batch.body.items) == 3
    # The assets table fits on one page; all intermediates empty; terminal
    # batch advances past the assets and emits from the last table.
    # But the first batch we get back here is from `assets` because that's
    # what the algorithm returns first when has_more_in_table is false but
    # the table itself had rows — we advance to next_table for the cursor.
    # Wait: when has_more_in_table=False and table is not _TABLES[-1] and
    # page_rows is non-empty, we emit a batch with body=Assets... and
    # cursor=encode(next_table=ASSET_FIELD_VALUES, last_id=None).
    assert batch.cursor is not None
    assert batch.event_log_cursor is None


async def test_multi_page_within_one_table(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    asset_ids = {
        (await _make_asset(session, type_id=asset_type.id)).id for _ in range(5)
    }

    seen_ids: set[UUID] = set()
    cursor: str | None = None
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=2)
        if isinstance(batch.body, AssetsBatchBody):
            for item in batch.body.items:
                assert item.id not in seen_ids, "no duplicates across pages"
                seen_ids.add(item.id)
        pages += 1
        if batch.cursor is None:
            assert batch.event_log_cursor == 0
            break
        cursor = batch.cursor
        assert pages < 20, "guard against runaway loop"

    assert seen_ids == asset_ids


async def test_cross_table_walk(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    mr_type = await _make_maintenance_record_type(session)
    asset = await _make_asset(session, type_id=asset_type.id)

    session.add(
        AssetFieldValue(
            tenant_id="t1",
            asset_id=asset.id,
            field_id="col:name",
            value_json="Truck-1",
            hlc="0001700000000000-00000-abc",
        )
    )
    mr = MaintenanceRecord(
        id=uuid4(),
        tenant_id="t1",
        type_id=mr_type.id,
        asset_id=asset.id,
        name=None,
        properties={},
        deleted=False,
        row_state_hlc="0001700000000001-00000-abc",
    )
    session.add(mr)
    await session.flush()
    session.add(
        MaintenanceRecordFieldValue(
            tenant_id="t1",
            maintenance_record_id=mr.id,
            field_id="col:name",
            value_json="Inspection-A",
            hlc="0001700000000001-00000-abc",
        )
    )
    await _make_event(
        session,
        hlc="0001700000000002-00000-abc",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    visited: list[type] = []
    cursor: str | None = None
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=10)
        visited.append(type(batch.body))
        if batch.cursor is None:
            assert batch.event_log_cursor == 1
            break
        cursor = batch.cursor
        pages += 1
        assert pages < 20, "guard"

    assert visited == [
        AssetsBatchBody,
        AssetFieldValuesBatchBody,
        MaintenanceRecordsBatchBody,
        MaintenanceRecordFieldValuesBatchBody,
    ]


async def test_skips_empty_intermediate_tables(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    mr_type = await _make_maintenance_record_type(session)
    asset = await _make_asset(session, type_id=asset_type.id)
    mr = MaintenanceRecord(
        id=uuid4(),
        tenant_id="t1",
        type_id=mr_type.id,
        asset_id=asset.id,
        name=None,
        properties={},
        deleted=False,
        row_state_hlc="0001700000000001-00000-abc",
    )
    session.add(mr)
    await session.flush()

    visited: list[type] = []
    cursor: str | None = None
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=10)
        visited.append(type(batch.body))
        if batch.cursor is None:
            break
        cursor = batch.cursor
        pages += 1
        assert pages < 20, "guard"

    assert AssetFieldValuesBatchBody not in visited
    assert AssetsBatchBody in visited
    assert MaintenanceRecordsBatchBody in visited
    # Last table is always emitted, possibly empty:
    assert visited[-1] is MaintenanceRecordFieldValuesBatchBody


async def test_start_seq_is_captured_at_first_request(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    asset = await _make_asset(session, type_id=asset_type.id)
    await _make_event(
        session,
        hlc="0001700000000000-00000-aaa",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    # First request — cursor=None — captures start_seq = current MAX(seq).
    batch1 = await paginator(cursor=None, results_per_page=1)
    assert batch1.cursor is not None

    # Insert a new event AFTER start_seq is captured.
    await _make_event(
        session,
        hlc="0001700000000001-00000-bbb",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    # Drive to terminal and check the cursor is the pre-extra seq. The
    # extra event raised MAX(seq) to 2, but the threaded start_seq is 1.
    cursor: str | None = batch1.cursor
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=1)
        if batch.cursor is None:
            assert batch.event_log_cursor == 1
            break
        cursor = batch.cursor
        pages += 1
        assert pages < 20, "guard"


async def test_schema_version_is_current_each_request(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    for _ in range(3):
        await _make_asset(session, type_id=asset_type.id)
    v1 = await _bump_schema_version(session)

    batch1 = await paginator(cursor=None, results_per_page=1)
    assert batch1.schema_version == v1

    v2 = await _bump_schema_version(session)
    assert v2 > v1

    batch2 = await paginator(cursor=batch1.cursor, results_per_page=1)
    assert batch2.schema_version == v2


async def test_bad_cursor_raises_payload_shape_error(
    paginator: InitialSyncPaginator,
) -> None:
    with pytest.raises(PayloadShapeError) as exc:
        await paginator(cursor="not-base64!@#", results_per_page=10)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE
