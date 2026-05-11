"""Per-event handler dispatch.

The handler table is enumerated explicitly below. Each
``(family, body_type)`` cell maps to the function that handles it.
Adding a new event body or family means writing the handler in the
appropriate ``_handlers/<family>.py`` module, then adding one row
here — the universe of accepted (family, body_type) pairs is one
``rg``-able place (Zen of Python item 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.domain.events import _payloads
from novamoc.domain.events._handlers import asset, maintenance_record
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle, Handler
    from novamoc.domain.events._payloads import EventEnvelope, EventOutcome


__all__ = ("dispatch",)


_HANDLERS: dict[tuple[EntityFamily, type], Handler] = {
    (EntityFamily.ASSET, _payloads.Created): asset.created,
    (EntityFamily.ASSET, _payloads.Updated): asset.updated,
    (EntityFamily.ASSET, _payloads.Deactivated): asset.deactivated,
    (EntityFamily.ASSET, _payloads.Activated): asset.activated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Created): (maintenance_record.created),
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Updated): (maintenance_record.updated),
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Deactivated): (
        maintenance_record.deactivated
    ),
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Activated): (
        maintenance_record.activated
    ),
}


async def dispatch(
    services: EventServiceBundle,
    auth: RequestAuth,
    event: EventEnvelope,
) -> EventOutcome:
    return await _HANDLERS[(event.family, type(event.body))](services, auth, event)
