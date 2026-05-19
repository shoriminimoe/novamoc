"""Unit tests for ``InitialSyncPaginator``.

Run against an in-memory aiosqlite engine — no mocks, per the project's
testing rule. Each test builds its services inline against the
``session`` fixture from ``tests/conftest.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._pagination import InitialSyncPaginator
from novamoc.domain.sync._payloads import MaintenanceRecordFieldValuesBatchBody
from novamoc.domain.sync.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)

if TYPE_CHECKING:
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
