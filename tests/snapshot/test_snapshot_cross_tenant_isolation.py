"""``SnapshotPaginator`` returns only the active tenant's rows.

Regression guard for the snapshot endpoint's tenant scoping. The
paginator carries no tenant predicate of its own — Layer 1 of
``db._listeners`` injects ``WHERE tenant_id = <ctx>`` on every ORM
SELECT against the four projection tables and on the ``current_seq``
/ ``current_version`` aggregates. Seeds equivalent rows under ``t-a``
and ``t-b``; under each tenant context, the bulk transfer must see
only its own data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.data import Asset
from novamoc.db.models.schema import AssetType
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.snapshot._pagination import SnapshotPaginator
from novamoc.domain.snapshot._payloads import AssetsBatchBody
from novamoc.domain.snapshot.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _paginator(session: AsyncSession) -> SnapshotPaginator:
    return SnapshotPaginator(
        change_log_service=SchemaChangeLogService(session=session),
        event_log_service=EventLogService(session=session),
        asset_service=AssetService(session=session),
        asset_field_value_service=AssetFieldValueService(session=session),
        maintenance_record_service=MaintenanceRecordService(session=session),
        maintenance_record_field_value_service=(
            MaintenanceRecordFieldValueService(session=session)
        ),
    )


async def _seed_asset(session: AsyncSession, *, tenant_id: str) -> tuple[UUID, UUID]:
    """Seed one asset_type + one asset under ``tenant_id``. Returns
    ``(type_id, asset_id)``."""
    type_id = uuid4()
    asset_id = uuid4()
    session.add(
        AssetType(id=type_id, tenant_id=tenant_id, name=f"Truck-{type_id}", active=True)
    )
    await session.flush()
    session.add(
        Asset(
            id=asset_id,
            tenant_id=tenant_id,
            type_id=type_id,
            name=None,
            properties={},
            deleted=False,
            row_state_hlc=f"0001700000000000-00000-{tenant_id}",
        )
    )
    await session.flush()
    return type_id, asset_id


async def _collect_asset_ids(
    paginator: SnapshotPaginator,
) -> set[UUID]:
    seen: set[UUID] = set()
    page: str | None = None
    pages = 0
    while True:
        batch = await paginator(page=page, results_per_page=100)
        if isinstance(batch.body, AssetsBatchBody):
            for item in batch.body.items:
                seen.add(item.id)
        if batch.page is None:
            break
        page = batch.page
        pages += 1
        assert pages < 20, "runaway-loop guard"
    return seen


async def test_paginator_isolates_tenants(session: AsyncSession) -> None:
    """Two tenants seed parallel data; each only sees its own assets."""
    # Pre-seed both tenants. The asset_type rows must come first so the
    # FK on Asset(type_id, tenant_id) resolves; use ``use_tenant`` so the
    # auto-stamp listener stamps the right tenant.
    with use_tenant("t-a"):
        _, asset_a = await _seed_asset(session, tenant_id="t-a")
    with use_tenant("t-b"):
        _, asset_b = await _seed_asset(session, tenant_id="t-b")

    paginator = _paginator(session)

    with use_tenant("t-a"):
        seen_a = await _collect_asset_ids(paginator)
    with use_tenant("t-b"):
        seen_b = await _collect_asset_ids(paginator)

    assert seen_a == {asset_a}
    assert seen_b == {asset_b}
    # Belt and braces: the other tenant's id must NOT appear.
    assert asset_b not in seen_a
    assert asset_a not in seen_b
