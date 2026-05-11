"""Maintenance-record-family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from novamoc.domain.events._payloads import (
    Activated,
    Deactivated,
    EntityFamily,
)
from novamoc.domain.events._validators import validate_values

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle
    from novamoc.domain.events._payloads import (
        Created,
        EventEnvelope,
        Updated,
    )


async def created(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast("Created", event.body)
    _ = auth  # reserved for M1.5+ tenant-scoped writes
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast("Updated", event.body)
    _ = auth  # reserved for M1.5+ tenant-scoped writes
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def deactivated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    _ = (services, auth, event, Deactivated)


async def activated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    _ = (services, auth, event, Activated)
