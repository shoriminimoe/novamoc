"""``EventLogCursorPaginator`` returns only the active tenant's events.

Regression guard for the catch-up endpoint's tenant scoping. The
paginator carries no tenant predicate of its own — Layer 1 of
``db._listeners`` injects ``WHERE tenant_id = <ctx>`` on every ORM
SELECT against ``event_log``. Seeds events for ``t-a`` and ``t-b``
interleaved at adjacent ``seq`` values; under each tenant context, the
catch-up must see only its own events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from novamoc.db._tenant_context import use_tenant
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._pagination import EventLogCursorPaginator
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B
from tests.data.seed_helpers import seed_asset_type

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _bundle(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )


async def _append(bundle: EventServiceBundle, hlc: str, type_id: UUID) -> None:
    await bundle.append_event(
        EventEnvelope(
            hlc=hlc,
            family=EntityFamily.ASSET,
            type_id=type_id,
            instance_id=uuid4(),
            body=Created(values={}),
        )
    )


async def test_paginator_isolates_tenants_at_interleaved_seqs(
    session: AsyncSession,
) -> None:
    """Interleaved append under two tenants — each tenant sees only its own."""
    bundle = _bundle(session)

    # Seed an ``asset_type`` row per tenant so the assets-projection FK
    # constraint (``foreign_keys=ON``) is satisfied when the Created events
    # fold into ``assets``.
    with use_tenant(DEV_TENANT_ID_A):
        type_id_a = await seed_asset_type(session)
    with use_tenant(DEV_TENANT_ID_B):
        type_id_b = await seed_asset_type(session)

    # Interleave: t-a, t-b, t-a, t-b, t-a → three events for t-a, two for t-b.
    with use_tenant(DEV_TENANT_ID_A):
        await _append(bundle, "0001700000000001-00000-aaa", type_id_a)
    with use_tenant(DEV_TENANT_ID_B):
        await _append(bundle, "0001700000000002-00000-bbb", type_id_b)
    with use_tenant(DEV_TENANT_ID_A):
        await _append(bundle, "0001700000000003-00000-aaa", type_id_a)
    with use_tenant(DEV_TENANT_ID_B):
        await _append(bundle, "0001700000000004-00000-bbb", type_id_b)
    with use_tenant(DEV_TENANT_ID_A):
        await _append(bundle, "0001700000000005-00000-aaa", type_id_a)

    paginator = EventLogCursorPaginator(EventLogService(session=session))

    with use_tenant(DEV_TENANT_ID_A):
        items_a, cursor_a = await paginator.get_items(cursor=None, results_per_page=100)
    with use_tenant(DEV_TENANT_ID_B):
        items_b, cursor_b = await paginator.get_items(cursor=None, results_per_page=100)

    assert {it.hlc for it in items_a} == {
        "0001700000000001-00000-aaa",
        "0001700000000003-00000-aaa",
        "0001700000000005-00000-aaa",
    }
    assert {it.hlc for it in items_b} == {
        "0001700000000002-00000-bbb",
        "0001700000000004-00000-bbb",
    }
    assert cursor_a is None
    assert cursor_b is None
