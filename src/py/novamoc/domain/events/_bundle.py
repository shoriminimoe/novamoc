"""Per-request aggregator of services + the field-set memo handlers use.

Lives here rather than in ``_dispatch`` or ``_handlers/__init__`` so both
can import it without setting up a circular dependency. The bundle is
built once per request in :class:`EventsController.append` and lives for
the duration of that handler call — schema cannot change mid-request, so
the memo has no invalidation surface.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from uuid import UUID

    from novamoc.db.models.schema import AssetTypeField, MaintenanceRecordTypeField
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._payloads import EventEnvelope
    from novamoc.domain.schema.services import (
        AssetTypeFieldService,
        MaintenanceRecordTypeFieldService,
    )


@dataclass(frozen=True, slots=True)
class EventServiceBundle:
    asset_type_field_service: AssetTypeFieldService
    maintenance_record_type_field_service: MaintenanceRecordTypeFieldService
    _fields_cache: dict[
        tuple[EntityFamily, UUID],
        dict[UUID, AssetTypeField | MaintenanceRecordTypeField],
    ] = field(default_factory=dict)

    async def fields_for(
        self, family: EntityFamily, type_id: UUID
    ) -> dict[UUID, AssetTypeField | MaintenanceRecordTypeField]:
        """Return ``type_id``'s field set, loading once per request.

        Subsequent calls for the same ``(family, type_id)`` return the
        cached dict without a DB round-trip.
        """
        key = (family, type_id)
        cached = self._fields_cache.get(key)
        if cached is not None:
            return cached
        service = (
            self.asset_type_field_service
            if family is EntityFamily.ASSET
            else self.maintenance_record_type_field_service
        )
        rows = await service.list(parent_id=type_id)
        loaded = {row.id: row for row in rows}
        self._fields_cache[key] = loaded
        return loaded


# Lazily-evaluated alias so the names used here can stay under TYPE_CHECKING.
type Handler = Callable[
    [EventServiceBundle, "RequestAuth", "EventEnvelope"], Awaitable[None]
]


__all__ = ("EventServiceBundle", "Handler")
