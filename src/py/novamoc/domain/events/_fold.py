"""LWW fold into the field-value projection tables (M1.6, ADR-007 / ADR-012).

The fold is one conditional upsert per (entity, field) per accepted
event. The HLC guard inside the SQL ``DO UPDATE WHERE`` clause makes
late-arriving events lose silently — a stale event observed via
catch-up sync does not overwrite a newer value already in the
projection.

The function returns the applied/skipped signal so the caller can
gate the downstream entity-table projection (M1.7): if the
``*_field_values`` upsert was skipped (a higher-HLC value already won)
the entity-table column / properties cell must not be touched, or the
two projections diverge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.sqlite import insert

from novamoc.db._tenant_context import current_tenant_id
from novamoc.db.models.data import AssetFieldValue, MaintenanceRecordFieldValue
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


# Per-family projection table + instance column name. Kept as a single
# table-of-truth so the fold logic stays generic over the family.
_PROJECTION = {
    EntityFamily.ASSET: (AssetFieldValue, "asset_id"),
    EntityFamily.MAINTENANCE_RECORD: (
        MaintenanceRecordFieldValue,
        "maintenance_record_id",
    ),
}


@dataclass(frozen=True, slots=True)
class FieldUpsert:
    """One cell to write into a ``*_field_values`` projection.

    Bundles the addressing tuple ``(family, instance_id, field_id)``
    with the value + HLC so :func:`apply_field_value` has a flat
    signature and call sites cannot accidentally transpose arguments.
    """

    family: EntityFamily
    instance_id: UUID
    field_id: str
    value: Any
    hlc: str


async def apply_field_value(session: AsyncSession, upsert: FieldUpsert) -> bool:
    """Conditionally upsert one row into the field-value projection.

    Returns ``True`` when the projection changed (insert or HLC-winning
    update); ``False`` when the existing row's HLC was greater than or
    equal to the new event's HLC and the row was left untouched.

    The HLC guard is the LWW rule from ADR-007: a stale event observed
    via catch-up sync must not overwrite a newer value already folded
    into the projection.
    """
    model, instance_col = _PROJECTION[upsert.family]
    tenant_id = current_tenant_id.get()
    if tenant_id is None:
        # The web layer's TenantContextMiddleware sets this before the
        # handler runs; tests get it from the autouse fixture. A None
        # here is a wiring bug, not a runtime condition.
        msg = "fold called without an active tenant in context"
        raise RuntimeError(msg)

    # ``model.__table__`` is a concrete ``Table`` at runtime; the SQLA
    # type stub widens it to ``FromClause``, which ``insert()`` does
    # not accept by stub signature. Runtime is fine — the stub is
    # being conservative — so suppress narrowing here rather than
    # introducing a cast we'd carry forever.
    table = model.__table__
    base = insert(table).values(  # ty: ignore[invalid-argument-type]
        tenant_id=tenant_id,
        field_id=upsert.field_id,
        value_json=upsert.value,
        hlc=upsert.hlc,
        **{instance_col: upsert.instance_id},
    )
    stmt = base.on_conflict_do_update(
        index_elements=["tenant_id", instance_col, "field_id"],
        set_={"value_json": base.excluded.value_json, "hlc": base.excluded.hlc},
        where=base.excluded.hlc > table.c.hlc,
    ).returning(table.c.hlc)

    result = await session.execute(stmt)
    # RETURNING yields a row iff the INSERT inserted or the DO UPDATE
    # actually ran (the WHERE clause passed). A skipped DO UPDATE
    # produces no row.
    return result.first() is not None


__all__ = ("apply_field_value",)
