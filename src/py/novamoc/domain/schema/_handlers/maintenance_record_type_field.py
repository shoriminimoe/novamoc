"""MaintenanceRecordTypeField command handlers.

Mirror of :mod:`novamoc.domain.schema._handlers.asset_type_field`
against the maintenance-record-type-field service. Per ADR-008
``create`` and ``activate`` are separate verbs; ``clear`` wipes the
data projection (``maintenance_record_field_values`` rows + the
field's key in each ``maintenance_records.properties`` JSON) in the
same transaction as the schema-change-log append (ADR-008 / ADR-019).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec
from advanced_alchemy.exceptions import IntegrityError

from novamoc.domain._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome
from novamoc.domain.schema._projection_wipe import FieldFamily, wipe_field_projection

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.schema import _payloads
    from novamoc.domain.schema._bundle import ServiceBundle


async def create(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.CreateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    parent = await services.maintenance_record_type.get_one_or_none(
        id=req.payload.parent_id,
    )
    if parent is None:
        raise ConflictError(code=ErrorCode.PARENT_TYPE_NOT_FOUND)
    try:
        await services.maintenance_record_type_field.create(
            data={
                "id": req.entity_id,
                "parent_id": req.payload.parent_id,
                "name": req.payload.name,
                "data_type": req.payload.data_type,
                "validation": req.payload.validation,
                "active": True,
            },
            auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(
            code=ErrorCode.NAME_RESERVED, name=req.payload.name
        ) from exc
    row = await services.change_log.append(
        command=SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CREATED, row.committed_at
    )


async def activate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.ActivateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        outcome = Outcome.NOOP
    else:
        await services.maintenance_record_type_field.update(
            data={"active": True},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    row = await services.change_log.append(
        command=SchemaCommand.ACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def update(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.UpdateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload)
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.maintenance_record_type_field.update(
            data=payload,
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        command=SchemaCommand.UPDATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.UPDATED, row.committed_at
    )


async def deactivate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.DeactivateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.maintenance_record_type_field.update(
            data={"active": False},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        command=SchemaCommand.DEACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def clear(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.ClearMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await wipe_field_projection(
        services.maintenance_record_type_field.repository.session,
        family=FieldFamily.MAINTENANCE_RECORD,
        tenant_id=auth.tenant_id,
        field_id=req.entity_id,
    )
    row = await services.change_log.append(
        command=SchemaCommand.CLEAR_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CLEARED, row.committed_at
    )


async def delete(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.DeleteMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.maintenance_record_type_field.delete(
        item_id=(auth.tenant_id, req.entity_id),
        auto_commit=False,
    )
    row = await services.change_log.append(
        command=SchemaCommand.DELETE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.DELETED, row.committed_at
    )
