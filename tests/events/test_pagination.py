"""``EventLogCursorPaginator`` unit tests against in-memory SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._pagination import EventLogCursorPaginator
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
    RecordedEvent,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.seed_helpers import seed_asset_type

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _append_n(
    bundle: EventServiceBundle, n: int, session: AsyncSession
) -> None:
    """Append N Created events for the active tenant."""
    type_id = await seed_asset_type(session)
    for i in range(n):
        await bundle.append_event(
            EventEnvelope(
                hlc=f"00017000000000{i:02d}-00000-abc",
                family=EntityFamily.ASSET,
                type_id=type_id,
                instance_id=uuid4(),
                body=Created(values={}),
            )
        )


@pytest.fixture
def paginator(session: AsyncSession) -> EventLogCursorPaginator:
    return EventLogCursorPaginator(EventLogService(session=session))


@pytest.fixture
def bundle(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )


async def test_get_items_empty_stream_returns_no_items_and_no_cursor(
    paginator: EventLogCursorPaginator,
) -> None:
    items, cursor = await paginator.get_items(cursor=None, results_per_page=10)
    assert items == []
    assert cursor is None


async def test_get_items_returns_all_when_under_page_size(
    paginator: EventLogCursorPaginator,
    bundle: EventServiceBundle,
    session: AsyncSession,
) -> None:
    await _append_n(bundle, 3, session)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=10)
    assert len(items) == 3
    assert all(isinstance(it, RecordedEvent) for it in items)
    assert [it.seq for it in items] == sorted(it.seq for it in items)
    assert cursor is None  # caught up


async def test_get_items_returns_first_page_and_signals_more(
    paginator: EventLogCursorPaginator,
    bundle: EventServiceBundle,
    session: AsyncSession,
) -> None:
    await _append_n(bundle, 5, session)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=2)
    assert len(items) == 2
    assert cursor == items[-1].seq


async def test_get_items_cursor_handoff_continues_stream(
    paginator: EventLogCursorPaginator,
    bundle: EventServiceBundle,
    session: AsyncSession,
) -> None:
    await _append_n(bundle, 5, session)
    page1, cursor1 = await paginator.get_items(cursor=None, results_per_page=2)
    page2, cursor2 = await paginator.get_items(cursor=cursor1, results_per_page=2)
    page3, cursor3 = await paginator.get_items(cursor=cursor2, results_per_page=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    assert cursor3 is None  # caught up

    all_seqs = [it.seq for it in page1 + page2 + page3]
    assert all_seqs == sorted(all_seqs)
    assert len(set(all_seqs)) == 5  # no duplicates


async def test_get_items_exact_page_boundary_signals_caught_up(
    paginator: EventLogCursorPaginator,
    bundle: EventServiceBundle,
    session: AsyncSession,
) -> None:
    await _append_n(bundle, 4, session)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=4)
    assert len(items) == 4
    assert cursor is None  # the +1 fetch returned only 4, so we're done
