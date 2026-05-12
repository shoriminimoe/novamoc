"""Per-request aggregator for the events handlers.

Holds the services + memo that handlers need and the
:meth:`append_event` helper that does the savepoint-isolated
``event_log`` insert. Built once per request in
:class:`EventsController.append` and lives for the duration of that
call — schema cannot change mid-request, so the memo has no
invalidation surface.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import msgspec
from advanced_alchemy.exceptions import IntegrityError as RepositoryIntegrityError

from novamoc.db.models.data import EventOp
from novamoc.domain.events._payloads import (
    Deactivated,
    EntityFamily,
    EventOutcome,
)

if TYPE_CHECKING:
    from uuid import UUID

    from novamoc.db.models.schema import AssetTypeField, MaintenanceRecordTypeField
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._payloads import EventBody, EventEnvelope
    from novamoc.domain.events.services import EventLogService
    from novamoc.domain.schema.services import (
        AssetTypeFieldService,
        MaintenanceRecordTypeFieldService,
    )


_TABLE_NAMES: Final[dict[EntityFamily, str]] = {
    EntityFamily.ASSET: "assets",
    EntityFamily.MAINTENANCE_RECORD: "maintenance_records",
}


def _op_for_body(body: EventBody) -> EventOp:
    """``deactivated`` events are deletes; everything else is a set."""
    if isinstance(body, Deactivated):
        return EventOp.DELETE
    return EventOp.SET


def _value_json_for_body(body: EventBody) -> dict[str, Any] | None:
    """``Deactivated`` carries no payload; everything else round-trips
    through msgspec to match the wire shape."""
    if isinstance(body, Deactivated):
        return None
    return msgspec.to_builtins(body)


@dataclass(frozen=True, slots=True)
class EventServiceBundle:
    asset_type_field_service: AssetTypeFieldService
    maintenance_record_type_field_service: MaintenanceRecordTypeFieldService
    event_log_service: EventLogService
    schema_version: int
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

    async def append_event(self, event: EventEnvelope) -> EventOutcome:
        """Insert one ``event_log`` row inside a savepoint.

        The savepoint isolates the ``IntegrityError`` path so the outer
        transaction (committed at response time by the autocommit
        handler) stays usable for subsequent events in the batch.

        Returns:
            ``accepted`` for a fresh insert, ``duplicate`` if the
            ``UNIQUE(tenant_id, hlc)`` constraint was hit.
        """
        session = self.event_log_service.repository.session
        try:
            async with session.begin_nested():
                await self.event_log_service.create(
                    data={
                        "hlc": event.hlc,
                        "schema_version": self.schema_version,
                        "table_name": _TABLE_NAMES[event.family],
                        "entity_id": str(event.instance_id),
                        "field_id": None,
                        "op": _op_for_body(event.body),
                        "value_json": _value_json_for_body(event.body),
                    },
                    auto_commit=False,
                )
        except RepositoryIntegrityError:
            # advanced_alchemy wraps SQLAlchemy IntegrityError into its
            # own taxonomy (DuplicateKeyError extends this). The
            # savepoint rolled back, so the outer transaction is still
            # usable.
            return EventOutcome(hlc=event.hlc, outcome="duplicate")
        return EventOutcome(hlc=event.hlc, outcome="accepted")


# Lazily-evaluated alias so the names used here can stay under TYPE_CHECKING.
type Handler = Callable[
    [EventServiceBundle, "RequestAuth", "EventEnvelope"], Awaitable[EventOutcome]
]


__all__ = ("EventServiceBundle", "Handler")
