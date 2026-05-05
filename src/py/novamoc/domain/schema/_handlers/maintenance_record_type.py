"""MaintenanceRecordType command handlers.

Mirror of :mod:`novamoc.domain.schema._handlers.asset_type` against the
maintenance-record-type service. Per ADR-008 ``create`` and ``activate``
are separate verbs.
"""

from __future__ import annotations

import msgspec
from advanced_alchemy.exceptions import IntegrityError

from novamoc.domain.accounts import RequestAuth
from novamoc.domain.schema import _payloads
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome


async def create(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.CreateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    try:
        await services.maintenance_record_type.create(
            data={
                "tenant_id": auth.tenant_id,
                "id": req.entity_id,
                "name": req.payload.name,
                "active": True,
            },
            auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(
            code=ErrorCode.NAME_RESERVED, name=req.payload.name
        ) from exc
    row = await services.change_log.append(
        tenant_id=auth.tenant_id,
        command=SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CREATED, row.committed_at
    )


async def activate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.ActivateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=auth.tenant_id,
        id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        outcome = Outcome.NOOP
    else:
        await services.maintenance_record_type.update(
            data={"active": True},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    row = await services.change_log.append(
        tenant_id=auth.tenant_id,
        command=SchemaCommand.ACTIVATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def update(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.UpdateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=auth.tenant_id,
        id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload)
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.maintenance_record_type.update(
            data=payload,
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=auth.tenant_id,
        command=SchemaCommand.UPDATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.UPDATED, row.committed_at
    )


async def deactivate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.DeactivateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=auth.tenant_id,
        id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.maintenance_record_type.update(
            data={"active": False},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        tenant_id=auth.tenant_id,
        command=SchemaCommand.DEACTIVATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def delete(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.DeleteMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=auth.tenant_id,
        id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.maintenance_record_type.delete(
        item_id=(auth.tenant_id, req.entity_id),
        auto_commit=False,
    )
    row = await services.change_log.append(
        tenant_id=auth.tenant_id,
        command=SchemaCommand.DELETE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.DELETED, row.committed_at
    )
