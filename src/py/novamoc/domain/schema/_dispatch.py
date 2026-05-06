"""Command dispatch.

The handler table is enumerated explicitly below. Each command struct
maps to the function that executes it. Adding a new verb means: write
the handler in the appropriate ``_handlers/<kind>.py`` module, then add
one line here. Explicit beats implicit (Zen of Python item 2) — the
universe of accepted commands is one ``rg``-able place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from novamoc.domain.schema import _payloads
from novamoc.domain.schema._handlers import (
    asset_type,
    asset_type_field,
    maintenance_record_type,
    maintenance_record_type_field,
)

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.schema._bundle import Handler, ServiceBundle
    from novamoc.domain.schema._outcomes import SchemaCommitOutcome

__all__ = ("dispatch",)


_HANDLERS: dict[type, Handler] = {
    _payloads.CreateAssetType: asset_type.create,
    _payloads.ActivateAssetType: asset_type.activate,
    _payloads.UpdateAssetType: asset_type.update,
    _payloads.DeactivateAssetType: asset_type.deactivate,
    _payloads.DeleteAssetType: asset_type.delete,
    _payloads.CreateAssetTypeField: asset_type_field.create,
    _payloads.ActivateAssetTypeField: asset_type_field.activate,
    _payloads.UpdateAssetTypeField: asset_type_field.update,
    _payloads.DeactivateAssetTypeField: asset_type_field.deactivate,
    _payloads.ClearAssetTypeField: asset_type_field.clear,
    _payloads.DeleteAssetTypeField: asset_type_field.delete,
    _payloads.CreateMaintenanceRecordType: maintenance_record_type.create,
    _payloads.ActivateMaintenanceRecordType: maintenance_record_type.activate,
    _payloads.UpdateMaintenanceRecordType: maintenance_record_type.update,
    _payloads.DeactivateMaintenanceRecordType: maintenance_record_type.deactivate,
    _payloads.DeleteMaintenanceRecordType: maintenance_record_type.delete,
    _payloads.CreateMaintenanceRecordTypeField: maintenance_record_type_field.create,
    _payloads.ActivateMaintenanceRecordTypeField: maintenance_record_type_field.activate,
    _payloads.UpdateMaintenanceRecordTypeField: maintenance_record_type_field.update,
    _payloads.DeactivateMaintenanceRecordTypeField: maintenance_record_type_field.deactivate,
    _payloads.ClearMaintenanceRecordTypeField: maintenance_record_type_field.clear,
    _payloads.DeleteMaintenanceRecordTypeField: maintenance_record_type_field.delete,
}


async def dispatch(
    services: ServiceBundle, auth: RequestAuth, request: Any
) -> SchemaCommitOutcome:
    return await _HANDLERS[type(request)](services, auth, request)
