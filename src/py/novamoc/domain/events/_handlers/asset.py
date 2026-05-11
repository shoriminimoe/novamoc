"""Asset-family event handlers.

Each function is one cell of the (family, body_type) dispatch matrix
(see ``_dispatch.py``). Created/updated handlers validate the
``values`` payload against the type's field set before persisting;
deactivated/activated handlers carry no payload and go straight to
the append.
"""

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
    _ = auth  # reserved for future tenant-scoped writes
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)
    return await services.append_event(event)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> EventOutcome:
    body = cast("Updated", event.body)
    _ = auth
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
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
