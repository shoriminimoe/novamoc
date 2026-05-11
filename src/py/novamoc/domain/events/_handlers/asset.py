"""Asset-family event handlers.

Each function is one cell of the (family, body_type) dispatch matrix
(see ``_dispatch.py``). In M1.4 the handlers do field/value validation
only; persistence and projection writes arrive with M1.5+ in the same
cells.
"""

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
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast("Updated", event.body)
    _ = auth  # reserved for M1.5+ tenant-scoped writes
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def deactivated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    # Row-state event; no field/value payload. M1.5+ adds the deactivate path.
    _ = (services, auth, event, Deactivated)


async def activated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    # Row-state event; no field/value payload. M1.5+ adds the activate path.
    _ = (services, auth, event, Activated)
