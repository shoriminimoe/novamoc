"""Maintenance-record-family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from novamoc.domain.events._payloads import EntityFamily
from novamoc.domain.events._validators import validate_values

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle
    from novamoc.domain.events._payloads import (
        Created,
        EventEnvelope,
        EventOutcome,
        Updated,
    )


async def created(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> EventOutcome:
    body = cast("Created", event.body)
    _ = auth
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)
    return await services.append_event(event)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> EventOutcome:
    body = cast("Updated", event.body)
    _ = auth
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)
    return await services.append_event(event)


async def deactivated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> EventOutcome:
    _ = auth
    return await services.append_event(event)


async def activated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> EventOutcome:
    _ = auth
    return await services.append_event(event)
