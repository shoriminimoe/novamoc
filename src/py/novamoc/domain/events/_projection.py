"""Entity-table projection updates (M1.7, ADR-005 / ADR-012 / ADR-019).

Each accepted-and-applied field-grain event mirrors into the entity
table so application reads can use ``json_extract(properties, ...)``
or the named columns without joining into ``*_field_values``. The
mirror is gated on the M1.6 fold's applied/skipped signal: a stale
event must not update the entity row when the field-value row was
rejected by the HLC guard, otherwise the two projections diverge.

User-field keys go into the ``properties`` JSON via ``json_set``;
``col:<name>`` keys target the named column directly. A ``null``
value is the cell-clearing sentinel (ADR-019, revising ADR-012) —
``json_set(..., NULL)`` for user fields so the key stays present
with JSON ``null``, and ``SET <col> = NULL`` for ``col:``.

The update is a no-op when the entity row does not exist yet — that's
the M1.8 row-state path (existence + restore). M1.7 + M1.8 together
form the full apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, update

from novamoc.db._tenant_context import current_tenant_id
from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.events._fold import FieldUpsert


_COL_PREFIX = "col:"

# Per-family entity table. Reusing the same EntityFamily dispatch as
# the fold keeps the family→table mapping in one place per module.
_ENTITY_TABLE = {
    EntityFamily.ASSET: Asset,
    EntityFamily.MAINTENANCE_RECORD: MaintenanceRecord,
}


def _properties_path(field_id: str) -> str:
    # JSON path needs a leading $. Field ids are UUID strings (no dots
    # or special chars) so naive concatenation is safe.
    return f"$.{field_id}"


def _value_expression(properties_col: Any, field_id: str, value: Any) -> Any:
    # ADR-019: a cleared user field stays in ``properties`` as JSON
    # null rather than being removed, so the entity's projection
    # reflects its full schema state.
    return func.json_set(properties_col, _properties_path(field_id), value)


async def apply_entity_projection(session: AsyncSession, upsert: FieldUpsert) -> None:
    """Mirror one field's value into the entity-table projection.

    A ``UPDATE ... WHERE id = ? AND tenant_id = ?`` that touches zero
    rows when the entity row has not been created yet (the row-state
    event runs in M1.8) — caller need not check existence first.
    """
    tenant_id = current_tenant_id.get()
    if tenant_id is None:
        msg = "entity projection called without an active tenant in context"
        raise RuntimeError(msg)

    model = _ENTITY_TABLE[upsert.family]
    # ``model.__table__`` resolves to a concrete Table at runtime; the
    # SQLA type stub widens it. Same suppression pattern as the fold.
    table = model.__table__
    stmt = update(table).where(  # ty: ignore[invalid-argument-type]
        table.c.tenant_id == tenant_id,
        table.c.id == upsert.instance_id,
    )

    if upsert.field_id.startswith(_COL_PREFIX):
        column_name = upsert.field_id[len(_COL_PREFIX) :]
        # A ``col:`` value of None resolves to SQL NULL via the bound
        # parameter — no extra null-handling needed.
        stmt = stmt.values({column_name: upsert.value})
    else:
        new_props = _value_expression(table.c.properties, upsert.field_id, upsert.value)
        stmt = stmt.values({"properties": new_props})

    await session.execute(stmt)


__all__ = ("apply_entity_projection",)
