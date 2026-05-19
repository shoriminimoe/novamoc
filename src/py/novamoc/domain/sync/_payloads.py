"""Wire-format structs for ``GET /sync/initial``.

The response is :class:`InitialSyncBatch`. Its ``body`` field is a
discriminated union tagged on ``table`` — one variant per projection
table — so each batch is a homogeneous list of one shape of row.

Row views deliberately *omit* the derived columns (``properties``,
``name``) from the projection tables: clients reconstruct them by
folding the per-field rows they receive, per ADR-015 §"Derived entity
JSON".

``forbid_unknown_fields=True`` on every struct so a wire-shape drift
shows up loudly in tests rather than silently dropping fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec


class AssetView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``assets`` projected for initial sync.

    Omits ``name`` (mirrors ``col:name``) and ``properties`` (derivable
    from the per-field rows the client also receives).
    """

    id: UUID
    type_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class AssetFieldValueView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``asset_field_values`` projected for initial sync.

    The fold unit. ``hlc`` is preserved so subsequent client-side LWW
    folds against incoming events behave correctly.
    """

    asset_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str


class MaintenanceRecordView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``maintenance_records`` projected for initial sync."""

    id: UUID
    type_id: UUID
    asset_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class MaintenanceRecordFieldValueView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``maintenance_record_field_values`` projected for sync."""

    maintenance_record_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str


class _SyncBody(msgspec.Struct, tag_field="table", forbid_unknown_fields=True):
    """Discriminator base for :data:`InitialSyncBody`.

    Subclasses set ``tag`` to the table name. The discriminator field
    is ``table``; msgspec publishes the union as ``oneOf`` in the
    OpenAPI schema. Per-struct config is inherited by subclasses, so
    setting ``forbid_unknown_fields`` here covers every ``*BatchBody``.
    """


class AssetsBatchBody(_SyncBody, tag="assets"):
    items: tuple[AssetView, ...]


class AssetFieldValuesBatchBody(_SyncBody, tag="asset_field_values"):
    items: tuple[AssetFieldValueView, ...]


class MaintenanceRecordsBatchBody(_SyncBody, tag="maintenance_records"):
    items: tuple[MaintenanceRecordView, ...]


class MaintenanceRecordFieldValuesBatchBody(
    _SyncBody, tag="maintenance_record_field_values"
):
    items: tuple[MaintenanceRecordFieldValueView, ...]


InitialSyncBody = (
    AssetsBatchBody
    | AssetFieldValuesBatchBody
    | MaintenanceRecordsBatchBody
    | MaintenanceRecordFieldValuesBatchBody
)


class InitialSyncBatch(msgspec.Struct, forbid_unknown_fields=True):
    """One batch of the initial-sync transfer.

    Attributes:
        schema_version: Server's current ``schema_version`` at request
            time. Advances across batches signal a schema change
            mid-transfer; client compares and restarts (ADR-015
            §"Consistency"). Per-batch internal consistency is provided
            by the single-request SQLite WAL snapshot.
        cursor: Opaque continuation. ``None`` ⇒ transfer complete.
            Non-null ⇒ pass back as ``?cursor=`` on the next request.
        event_log_cursor: ``MAX(event_log.seq)`` captured at the start
            of the transfer. Present only when ``cursor`` is ``None``
            (terminal batch); ``None`` on every intermediate batch.
            Client passes this to ``GET /events?cursor=`` to start
            incremental catch-up (M2.4) and as the WS hello cursor (M3).
        body: Discriminated body — one ``items`` list for one projection
            table.
    """

    schema_version: int
    cursor: str | None
    event_log_cursor: int | None
    body: InitialSyncBody


__all__ = (
    "AssetFieldValueView",
    "AssetFieldValuesBatchBody",
    "AssetView",
    "AssetsBatchBody",
    "InitialSyncBatch",
    "InitialSyncBody",
    "MaintenanceRecordFieldValueView",
    "MaintenanceRecordFieldValuesBatchBody",
    "MaintenanceRecordView",
    "MaintenanceRecordsBatchBody",
)
