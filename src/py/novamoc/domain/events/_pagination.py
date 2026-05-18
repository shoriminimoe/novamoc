"""Cursor-paginated reader over ``event_log`` for the active tenant.

The HTTP catch-up endpoint (M2.4, ADR-013 §"HTTP `/sync`") streams
recorded events to a returning client. The M3 WebSocket fan-out emits
the same :class:`RecordedEvent` envelope so the wire format is
identical regardless of transport.

Tenant scoping is structural: Layer 1 of :mod:`db._listeners` injects
``WHERE tenant_id = <ctx>`` on every ORM SELECT against ``event_log``,
so the paginator carries no tenant predicate of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from litestar.pagination import AbstractAsyncCursorPaginator

from novamoc.db.models.data import EventLog
from novamoc.domain.events._bundle import _FAMILY_BY_TABLE_NAME, body_from_row
from novamoc.domain.events._payloads import RecordedEvent

if TYPE_CHECKING:
    from novamoc.domain.events.services import EventLogService


def _row_to_recorded_event(row: EventLog) -> RecordedEvent:
    """Project an ``event_log`` row into the :class:`RecordedEvent` wire
    shape."""
    return RecordedEvent(
        seq=row.seq,
        schema_version=row.schema_version,
        hlc=row.hlc,
        family=_FAMILY_BY_TABLE_NAME[row.table_name],
        type_id=UUID(row.type_id),
        instance_id=UUID(row.entity_id),
        body=body_from_row(row),
        received_at=row.received_at,
    )


class EventLogCursorPaginator(AbstractAsyncCursorPaginator[int, RecordedEvent]):
    """Cursor pagination over ``event_log`` rows for the active tenant.

    Cursor semantics:

    * ``cursor=None`` — start from the beginning of the tenant's stream.
    * ``cursor=N`` — return rows with ``seq > N`` (exclusive, ADR-011).
    * Returned cursor is the ``seq`` of the last row when more rows
      remain, or ``None`` when the caller has reached the end.

    Implementation fetches ``results_per_page + 1`` to detect overflow
    without a separate ``COUNT``.
    """

    def __init__(self, event_log_service: EventLogService) -> None:
        self._service = event_log_service

    async def get_items(
        self, cursor: int | None, results_per_page: int
    ) -> tuple[list[RecordedEvent], int | None]:
        order_by = OrderBy(field_name="seq")
        limit_offset = LimitOffset(limit=results_per_page + 1, offset=0)
        if cursor is not None:
            rows = await self._service.list(
                EventLog.seq > cursor, order_by, limit_offset
            )
        else:
            rows = await self._service.list(order_by, limit_offset)

        has_more = len(rows) > results_per_page
        page = rows[:results_per_page]
        items = [_row_to_recorded_event(row) for row in page]
        next_cursor = page[-1].seq if has_more else None
        return items, next_cursor
