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

if TYPE_CHECKING:
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


async def _append(bundle: EventServiceBundle, hlc: str) -> None:
    await bundle.append_event(
        EventEnvelope(
            hlc=hlc,
            family=EntityFamily.ASSET,
            type_id=uuid4(),
            instance_id=uuid4(),
            body=Created(values={}),
        )
    )


async def test_paginator_isolates_tenants_at_interleaved_seqs(
    session: AsyncSession,
) -> None:
    """Interleaved append under two tenants — each tenant sees only its own."""
    bundle = _bundle(session)

    # Interleave: t-a, t-b, t-a, t-b, t-a → three events for t-a, two for t-b.
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000001-00000-aaa")
    with use_tenant("t-b"):
        await _append(bundle, "0001700000000002-00000-bbb")
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000003-00000-aaa")
    with use_tenant("t-b"):
        await _append(bundle, "0001700000000004-00000-bbb")
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000005-00000-aaa")

    paginator = EventLogCursorPaginator(EventLogService(session=session))

    with use_tenant("t-a"):
        items_a, cursor_a = await paginator.get_items(cursor=None, results_per_page=100)
    with use_tenant("t-b"):
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
