"""``event_log.type_id`` is populated on every accepted event (spec §Storage)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from novamoc.db.models.data import EventLog
from novamoc.domain.events._bundle import EventServiceBundle
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
from tests.data.scenarios import ACTIVE_TRUCK

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.data.scenarios import Scenario


async def test_append_event_persists_type_id(
    session: AsyncSession,
    seed: Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK)
    type_id = ids["asset_type"]["Truck"]
    instance_id = uuid4()
    bundle = EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )

    await bundle.append_event(
        EventEnvelope(
            hlc="0001700000000000-00000-abc",
            family=EntityFamily.ASSET,
            type_id=type_id,
            instance_id=instance_id,
            body=Created(values={}),
        )
    )

    result = await session.execute(select(EventLog).limit(1))
    row = result.scalar_one()
    assert row.type_id == str(type_id)
    assert row.entity_id == str(instance_id)
