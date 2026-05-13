"""Row-level event apply (M1.8, ADR-012).

Row-level events carry ``field_id IS NULL`` and toggle the visibility
of an entire entity by writing ``deleted`` + ``row_state_hlc`` on the
entity table. Field-grain events fold into ``*_field_values``
regardless of visibility (ADR-012's "data fold decoupled from schema
visibility"); only the row-state bit is touched here.

Wire-event mapping:

* ``Created``  → insert-or-upsert the entity row with ``deleted=0`` and
  the event's HLC as ``row_state_hlc``. Initial field values land in
  ``properties`` / named columns by way of M1.6 + M1.7 running over
  the same wire event afterwards.
* ``Activated`` → UPDATE-only ``deleted=0`` with HLC guard. Missing
  rows are a no-op — restoration requires a row that has been seen.
* ``Deactivated`` → UPDATE-only ``deleted=1`` with HLC guard.
* ``Updated`` → no row-state action.

The HLC guard is strict-greater (same rule as ADR-007's per-field
fold) so a stale row-state event observed via catch-up sync cannot
flip the visibility bit when a newer event has already won.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert

from novamoc.db._tenant_context import current_tenant_id
from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    Updated,
)

if TYPE_CHECKING:
    from novamoc.domain.events._payloads import EventEnvelope


_ENTITY_MODEL = {
    EntityFamily.ASSET: Asset,
    EntityFamily.MAINTENANCE_RECORD: MaintenanceRecord,
}


def _require_tenant() -> str:
    tenant_id = current_tenant_id.get()
    if tenant_id is None:
        msg = "row-state apply called without an active tenant in context"
        raise RuntimeError(msg)
    return tenant_id


async def _apply_create(session, event: EventEnvelope) -> bool:
    """Insert the entity row if missing; else upsert ``deleted=0`` under
    the strict-greater HLC guard. Returns True if the row state changed.
    """
    tenant_id = _require_tenant()
    model = _ENTITY_MODEL[event.family]
    table = model.__table__

    base_values: dict[str, object] = {
        "tenant_id": tenant_id,
        "id": event.instance_id,
        "type_id": event.type_id,
        "name": None,
        "properties": {},
        "deleted": False,
        "row_state_hlc": event.hlc,
    }
    body = event.body
    if event.family is EntityFamily.MAINTENANCE_RECORD:
        if not isinstance(body, Created) or body.parent is None:
            # Created MR without a parent is a wire-shape error. Raise a
            # DomainError so the controller's catch maps it to
            # rejected:invalid_payload_shape rather than a 500.
            raise PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message="Created MR event missing parent reference",
                hlc=event.hlc,
            )
        base_values["asset_id"] = body.parent.instance_id

    base = insert(table).values(base_values)  # ty: ignore[invalid-argument-type]
    stmt = base.on_conflict_do_update(
        index_elements=["tenant_id", "id"],
        set_={
            "deleted": False,
            "row_state_hlc": base.excluded.row_state_hlc,
        },
        where=base.excluded.row_state_hlc > table.c.row_state_hlc,
    ).returning(table.c.row_state_hlc)
    result = await session.execute(stmt)
    return result.first() is not None


async def _apply_toggle(session, event: EventEnvelope, *, deleted: bool) -> bool:
    """UPDATE the entity row's deleted/row_state_hlc under the HLC guard.

    No INSERT path — Activated / Deactivated on a missing row is a
    no-op. Restoration requires a row that exists; deactivation of an
    unseen entity is meaningless.
    """
    tenant_id = _require_tenant()
    model = _ENTITY_MODEL[event.family]
    table = model.__table__
    stmt = (
        update(table)  # ty: ignore[invalid-argument-type]
        .where(
            table.c.tenant_id == tenant_id,
            table.c.id == event.instance_id,
            table.c.row_state_hlc < event.hlc,
        )
        .values(deleted=deleted, row_state_hlc=event.hlc)
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


async def apply_row_state(session, event: EventEnvelope) -> bool:
    """Apply one wire event's row-state component.

    Returns True if the entity row's row-state changed (newly inserted
    or visibility flipped). False covers no-op cases: ``Updated``
    events, stale HLCs, and UPDATE-only operations whose entity row
    has not yet been created.
    """
    body = event.body
    if isinstance(body, Updated):
        return False
    if isinstance(body, Created):
        return await _apply_create(session, event)
    if isinstance(body, Activated):
        return await _apply_toggle(session, event, deleted=False)
    if isinstance(body, Deactivated):
        return await _apply_toggle(session, event, deleted=True)
    msg = f"unhandled event body type: {type(body).__name__}"
    raise AssertionError(msg)


__all__ = ("apply_row_state",)
