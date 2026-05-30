"""Data-projection wipe for ``clear_*_field`` (issue #7, ADR-008 / ADR-019).

A ``clear_*_field`` schema command is the only schema verb that touches the
**data** projection: per ADR-008 it "wipes ``*_field_values`` rows for that
``field_id`` and removes the field's key from each affected ``properties``
JSON", as amended by ADR-019 which keeps the JSON key present with value
``null`` rather than removing it.

This module owns both halves of that wipe so the schema handler can express
the data-projection concern in one call. The work is two Core SQL statements
per family:

1. ``DELETE FROM <family>_field_values WHERE tenant_id = ? AND field_id = ?``
2. ``UPDATE <family> SET properties = json_set(properties, '$.<field_id>',
   NULL) WHERE tenant_id = ? AND json_type(properties, '$.<field_id>')
   IS NOT NULL``

Step 2's ``json_type IS NOT NULL`` predicate guards the ADR-019 invariant
("fields appear only after their first write" — never-touched fields stay
absent from ``properties``). It also makes the wipe idempotent: a second
clear finds JSON ``null`` already there (``json_type`` returns ``'null'``,
the string), re-applies ``json_set(..., NULL)``, and the value stays JSON
``null``.

Tenant scoping is structural — the ``tenant_id`` predicates in the WHERE
clauses are what Layer 3 of ``db._listeners`` checks for; without them the
DML would be rejected. The auto-commit before-send-handler commits the
schema-handler's whole transaction, so these writes land atomically with
the ``schema_change_log`` append.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, update

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FieldFamily(StrEnum):
    """Which projection-family a ``clear_*_field`` command targets.

    The schema-side field kinds (``asset_type_field`` /
    ``maintenance_record_type_field``) map 1:1 to a data-projection family;
    the same field UUID is the projection's ``field_id`` value.
    """

    ASSET = "asset"
    MAINTENANCE_RECORD = "maintenance_record"


# Per-family (entity table, field-value table) tuple. Same shape as the
# fold-side ``_ENTITY_TABLE`` map in ``domain/events/_projection.py``.
_TABLES = {
    FieldFamily.ASSET: (Asset, AssetFieldValue),
    FieldFamily.MAINTENANCE_RECORD: (MaintenanceRecord, MaintenanceRecordFieldValue),
}


def _properties_path(field_id: str) -> str:
    # Field ids are UUID strings (no dots / special chars), so naive
    # concatenation produces a valid SQLite JSON path.
    return f"$.{field_id}"


async def wipe_field_projection(
    session: AsyncSession,
    *,
    family: FieldFamily,
    tenant_id: UUID,
    field_id: UUID,
) -> None:
    """Wipe ``field_id``'s rows from the data projection for ``tenant_id``.

    Two Core SQL statements (see module docstring). Caller is responsible
    for not committing — the schema controller's ``autocommit`` before-send
    handler commits the whole transaction at response time.
    """
    entity_model, field_value_model = _TABLES[family]
    field_id_str = str(field_id)
    path = _properties_path(field_id_str)

    # ``model.__table__`` resolves to a concrete Table at runtime; the SQLA
    # type stub widens it. Same suppression pattern as the events projection.
    fv_table = field_value_model.__table__
    entity_table = entity_model.__table__

    await session.execute(
        delete(fv_table).where(  # ty: ignore[invalid-argument-type]
            fv_table.c.tenant_id == tenant_id,
            fv_table.c.field_id == field_id_str,
        )
    )

    await session.execute(
        update(entity_table)  # ty: ignore[invalid-argument-type]
        .where(
            entity_table.c.tenant_id == tenant_id,
            # ADR-019: only touch rows where the field was previously
            # written. ``json_type`` returns SQL NULL when the path is
            # absent and a string ('null', 'text', 'integer', ...) when
            # present. ``IS NOT NULL`` filters to "key exists in JSON".
            func.json_type(entity_table.c.properties, path).is_not(None),
        )
        .values({"properties": func.json_set(entity_table.c.properties, path, None)})
    )


__all__ = ("FieldFamily", "wipe_field_projection")
