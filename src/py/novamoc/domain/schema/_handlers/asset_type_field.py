"""AssetTypeField command handlers.

Per ADR-008 ``create`` and ``activate`` are separate verbs: ``create``
takes a full payload (parent_id, name, data_type, optional
validation) and inserts a new row; ``activate`` takes ``{}`` and only
flips ``active = true`` on an existing row. ``create`` validates that
the parent asset_type exists; a deactivated parent is allowed.

``clear`` (ADR-008) wipes the field's rows from the data projection
in the same transaction as the schema-change-log append: every
``asset_field_values`` row with ``field_id = <entity_id>`` is deleted,
and every ``assets.properties`` JSON that contains the key is rewritten
to set the value to JSON ``null`` (ADR-019). The actual SQL lives in
:mod:`novamoc.domain.schema._projection_wipe`.
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
    services: ServiceBundle, auth: RequestAuth, req: _payloads.CreateAssetTypeField
) -> SchemaCommitOutcome:
    parent = await services.asset_type.get_one_or_none(
        id=req.payload.parent_id,
    )
    if parent is None:
        raise ConflictError(code=ErrorCode.PARENT_TYPE_NOT_FOUND)
    try:
        await services.asset_type_field.create(
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
        command=SchemaCommand.CREATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CREATED, row.committed_at
    )


async def activate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.ActivateAssetTypeField,
) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        outcome = Outcome.NOOP
    else:
        await services.asset_type_field.update(
            data={"active": True},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    row = await services.change_log.append(
        command=SchemaCommand.ACTIVATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def update(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.UpdateAssetTypeField
) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    # ``omit_defaults=True`` on the payload struct drops UNSET fields here;
    # an explicit ``null`` on the wire stays as ``None`` so the handler can
    # write NULL to a nullable column.
    payload = msgspec.to_builtins(req.payload)
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.asset_type_field.update(
            data=payload,
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
    except IntegrityError as exc:
        # See note in update_asset_type — IntegrityError → NAME_RESERVED.
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        command=SchemaCommand.UPDATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.UPDATED, row.committed_at
    )


async def deactivate(
    services: ServiceBundle,
    auth: RequestAuth,
    req: _payloads.DeactivateAssetTypeField,
) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.asset_type_field.update(
            data={"active": False},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        command=SchemaCommand.DEACTIVATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def clear(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.ClearAssetTypeField
) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await wipe_field_projection(
        services.asset_type_field.repository.session,
        family=FieldFamily.ASSET,
        tenant_id=auth.tenant_id,
        field_id=req.entity_id,
    )
    row = await services.change_log.append(
        command=SchemaCommand.CLEAR_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CLEARED, row.committed_at
    )


async def delete(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.DeleteAssetTypeField
) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.asset_type_field.delete(
        item_id=(auth.tenant_id, req.entity_id),
        auto_commit=False,
    )
    row = await services.change_log.append(
        command=SchemaCommand.DELETE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.DELETED, row.committed_at
    )
