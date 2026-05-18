"""Wire-format response structs for ``GET /schema``.

Kept separate from :mod:`novamoc.domain.schema._payloads` (which holds
the command-side discriminated union) so the two concerns don't pile
into one file. View structs are passive shapes — no discriminator, no
defaults — they exist so the controller can hand a typed object to the
serializer instead of a hand-built dict.

Field nesting mirrors the conceptual shape (a type owns its fields).
``active`` is included on every row; clients filter at read time per use
case (see ADR-008 / ADR-009 / the design spec).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec

from novamoc.db.models.schema import FieldDataType


class AssetTypeFieldView(msgspec.Struct):
    id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None
    active: bool


class AssetTypeView(msgspec.Struct):
    id: UUID
    name: str
    active: bool
    fields: tuple[AssetTypeFieldView, ...]


class MaintenanceRecordTypeFieldView(msgspec.Struct):
    id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None
    active: bool


class MaintenanceRecordTypeView(msgspec.Struct):
    id: UUID
    name: str
    active: bool
    fields: tuple[MaintenanceRecordTypeFieldView, ...]


class SchemaSnapshotResponse(msgspec.Struct):
    schema_version: int
    asset_types: tuple[AssetTypeView, ...]
    maintenance_record_types: tuple[MaintenanceRecordTypeView, ...]


class SchemaChangeView(msgspec.Struct):
    """One row of ``schema_change_log`` on the wire.

    ``payload`` is passed through from the ``JsonB`` column as-is — the
    read path does NOT round-trip through the command-side
    ``_payloads.py`` structs. See the design spec for the rationale
    (rename-compatibility with historical rows; the payload was already
    validated at POST time).

    The envelope is :class:`litestar.pagination.CursorPagination` —
    ``items``, ``results_per_page``, ``cursor`` (None when caught up).
    ``schema_version`` is not in the envelope; clients learn it from
    ``GET /schema``'s ETag.
    """

    seq: int
    command: str
    entity_id: UUID
    payload: dict[str, Any]
    committed_at: datetime
    actor_id: str | None
