"""Wire-format structs for ``POST /schema``.

Each command is a subclass of :class:`_SchemaCommand`, which sets up
msgspec's default ``type`` discriminator field via a ``tag`` callable
that snake-cases the class name (``ActivateAssetType`` →
``activate_asset_type``). The 18 subclasses form ``SchemaRequest``, the
discriminated union Litestar publishes as a ``oneOf`` (by ``type``) in
the OpenAPI schema. Per-command payload shapes are kept as private
structs (``_*``).

**On the activate-payload shape.** msgspec rejects a field whose type
is a union of two untagged Structs, so the spec's ``definition |
_Empty`` shape can't be expressed directly without polluting the wire
format with an inner discriminator tag. Instead, ``activate_*``
commands carry a single payload struct with all fields optional: an
empty wire ``{}`` decodes to a struct whose fields are all ``None``
(the handler reads this as "empty intent" — activate-no-op), and
a populated wire decodes to a struct with the create-shape fields set
("create intent"). ``forbid_unknown_fields=True`` keeps unknown keys
from being silently accepted. See the design spec for the rationale.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import re

import msgspec
from msgspec import UNSET, UnsetType

from novamoc.db.models.schema import FieldDataType


def _snake_tag(cls_name: str) -> str:
    """Convert ``ActivateAssetType`` → ``activate_asset_type`` for the
    msgspec tag value. Used as the ``tag`` callable on the discriminator
    base class so each subclass auto-derives its tag from its class name.
    """

    return re.sub(r"(?<!^)(?=[A-Z])", "_", cls_name).lower()


class _SchemaCommand(msgspec.Struct, tag=_snake_tag):
    """Base class for the discriminated union of schema commands.

    Subclasses inherit msgspec's default ``type`` tag field plus a
    snake-case tag value derived from the class name. Adding a new
    command variant is just a new subclass — no per-class ``tag=`` line.
    """


class _Empty(msgspec.Struct, forbid_unknown_fields=True):
    """Marker struct for commands whose payload must be ``{}``.

    Used by ``deactivate_*``, ``delete_*``, and ``clear_*_field``
    commands. ``forbid_unknown_fields=True`` makes ``{"x": 1}`` a
    decoder error rather than a silently-accepted empty struct.
    """


# --- AssetType payload shapes ---


class _AssetTypeCreatePayload(msgspec.Struct, forbid_unknown_fields=True):
    """Payload for ``create_asset_type``. ``name`` is required."""

    name: str


class _AssetTypeUpdatePayload(
    msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True
):
    """Payload for ``update_asset_type`` — only changed properties.

    Empty wire ``{}`` is rejected by the handler as ``payload_no_changes``.
    Fields default to ``UNSET`` so absent-from-wire is distinguishable from
    explicit ``null`` (consistent with the field-level update payloads).
    """

    name: str | UnsetType = UNSET


# --- AssetType command structs ---


class CreateAssetType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeCreatePayload


class ActivateAssetType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class UpdateAssetType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeUpdatePayload


class DeactivateAssetType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class DeleteAssetType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


# --- AssetTypeField payload shapes ---


class _AssetTypeFieldCreatePayload(
    msgspec.Struct,
    forbid_unknown_fields=True,
    omit_defaults=True,
):
    """Payload for ``create_asset_type_field``.

    ``parent_id``, ``name``, and ``data_type`` are required;
    ``validation`` is optional.
    """

    parent_id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None = None


class _AssetTypeFieldUpdatePayload(
    msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True
):
    """Payload for ``update_asset_type_field`` — only changed properties.

    Note: ``parent_id`` is intentionally omitted — re-parenting a
    field is not an update operation.

    Nullable fields (``validation``) use ``UNSET`` as the default so that
    ``{"validation": null}`` on the wire is distinguishable from "field
    absent": absent → ``UNSET`` (skipped by the handler), explicit null →
    ``None`` (writes NULL to the column).
    """

    name: str | UnsetType = UNSET
    data_type: FieldDataType | UnsetType = UNSET
    validation: dict[str, Any] | None | UnsetType = UNSET


# --- AssetTypeField command structs ---


class CreateAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeFieldCreatePayload


class ActivateAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class UpdateAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeFieldUpdatePayload


class DeactivateAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class ClearAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class DeleteAssetTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


# --- MaintenanceRecordType payload shapes ---


class _MaintenanceRecordTypeCreatePayload(
    msgspec.Struct,
    forbid_unknown_fields=True,
):
    """Payload for ``create_maintenance_record_type``. ``name`` is required."""

    name: str


class _MaintenanceRecordTypeUpdatePayload(
    msgspec.Struct,
    forbid_unknown_fields=True,
    omit_defaults=True,
):
    """Payload for ``update_maintenance_record_type`` — only changed properties."""

    name: str | UnsetType = UNSET


# --- MaintenanceRecordType command structs ---


class CreateMaintenanceRecordType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeCreatePayload


class ActivateMaintenanceRecordType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class UpdateMaintenanceRecordType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeUpdatePayload


class DeactivateMaintenanceRecordType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class DeleteMaintenanceRecordType(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


# --- MaintenanceRecordTypeField payload shapes ---


class _MaintenanceRecordTypeFieldCreatePayload(
    msgspec.Struct,
    forbid_unknown_fields=True,
    omit_defaults=True,
):
    """Payload for ``create_maintenance_record_type_field``.

    ``parent_id``, ``name``, and ``data_type`` are required;
    ``validation`` is optional.
    """

    parent_id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None = None


class _MaintenanceRecordTypeFieldUpdatePayload(
    msgspec.Struct,
    forbid_unknown_fields=True,
    omit_defaults=True,
):
    """Payload for ``update_maintenance_record_type_field`` — only changed properties.

    Nullable fields use ``UNSET`` so ``{"validation": null}`` clears the
    column whereas an absent key leaves it untouched. See
    :class:`_AssetTypeFieldUpdatePayload` for the same pattern.
    """

    name: str | UnsetType = UNSET
    data_type: FieldDataType | UnsetType = UNSET
    validation: dict[str, Any] | None | UnsetType = UNSET


class CreateMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeFieldCreatePayload


class ActivateMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class UpdateMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeFieldUpdatePayload


class DeactivateMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class ClearMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


class DeleteMaintenanceRecordTypeField(_SchemaCommand):
    tenant_id: str
    entity_id: UUID
    payload: _Empty | UnsetType = UNSET


# --- The discriminated union ---

SchemaRequest = (
    CreateAssetType
    | ActivateAssetType
    | UpdateAssetType
    | DeactivateAssetType
    | DeleteAssetType
    | CreateAssetTypeField
    | ActivateAssetTypeField
    | UpdateAssetTypeField
    | DeactivateAssetTypeField
    | ClearAssetTypeField
    | DeleteAssetTypeField
    | CreateMaintenanceRecordType
    | ActivateMaintenanceRecordType
    | UpdateMaintenanceRecordType
    | DeactivateMaintenanceRecordType
    | DeleteMaintenanceRecordType
    | CreateMaintenanceRecordTypeField
    | ActivateMaintenanceRecordTypeField
    | UpdateMaintenanceRecordTypeField
    | DeactivateMaintenanceRecordTypeField
    | ClearMaintenanceRecordTypeField
    | DeleteMaintenanceRecordTypeField
)


# --- Response envelopes ---


class SchemaResponse(msgspec.Struct):
    schema_version: int
    entity_id: UUID
    outcome: str  # value of an Outcome enum member
    committed_at: datetime


class SchemaErrorResponse(msgspec.Struct, omit_defaults=True):
    error: str  # "invalid_request" | "conflict" | "not_found"
    code: str
    message: str
