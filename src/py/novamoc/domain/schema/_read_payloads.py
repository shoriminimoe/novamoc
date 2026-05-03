"""Wire-format response structs for ``GET /schema/{tenant_id}``.

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
