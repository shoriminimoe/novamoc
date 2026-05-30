"""AssetType command handlers.

Each handler reads the projection, validates the transition, mutates the
projection (``auto_commit=False``), and appends a ``schema_change_log``
row. A successful return yields a :class:`SchemaCommitOutcome` whose
``schema_version`` is the appended row's ``seq``.

Per ADR-008 ``create`` and ``activate`` are separate verbs: ``create``
takes a full payload and inserts a new row; ``activate`` takes ``{}``
and only flips ``active = true`` on an existing row.
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

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.schema import _payloads
    from novamoc.domain.schema._bundle import ServiceBundle


async def create(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.CreateAssetType
) -> SchemaCommitOutcome:
    existing = await services.asset_type.get_one_or_none(name=req.payload.name)
    if existing is not None:
        raise ConflictError(
            code=ErrorCode.NAME_RESERVED,
            name=req.payload.name,
            existing_name=existing.name,
        )
    try:
        await services.asset_type.create(
            data={
                "id": req.entity_id,
                "name": req.payload.name,
                "active": True,
            },
            auto_commit=False,
        )
    except IntegrityError as exc:
        # PK collision on (tenant_id, id) or UNIQUE on (tenant_id, name).
        raise ConflictError(
            code=ErrorCode.NAME_RESERVED, name=req.payload.name
        ) from exc
    row = await services.change_log.append(
        command=SchemaCommand.CREATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.CREATED, row.committed_at
    )


async def activate(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.ActivateAssetType
) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        outcome = Outcome.NOOP
    else:
        await services.asset_type.update(
            data={"active": True},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    row = await services.change_log.append(
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def update(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.UpdateAssetType
) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    # ``omit_defaults=True`` on the payload struct drops UNSET fields here;
    # an explicit ``null`` on the wire stays as ``None`` so the handler can
    # write NULL to a nullable column.
    payload = msgspec.to_builtins(req.payload)
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    new_name = payload.get("name")
    if new_name is not None:
        # Skip a same-id match: that's just a case-only rename on self.
        existing = await services.asset_type.get_one_or_none(name=new_name)
        if existing is not None and existing.id != req.entity_id:
            raise ConflictError(
                code=ErrorCode.NAME_RESERVED,
                name=new_name,
                existing_name=existing.name,
            )
    try:
        await services.asset_type.update(
            data=payload,
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
    except IntegrityError as exc:
        # Note: this maps every IntegrityError to NAME_RESERVED. The current
        # schema only has UNIQUE constraints reachable from update payloads, so
        # this is correct in practice. If schema columns ever gain CHECK / NOT
        # NULL constraints reachable from update, distinguish error causes by
        # inspecting the underlying constraint name.
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        command=SchemaCommand.UPDATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.UPDATED, row.committed_at
    )


async def deactivate(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.DeactivateAssetType
) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.asset_type.update(
            data={"active": False},
            item_id=(auth.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        command=SchemaCommand.DEACTIVATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def delete(
    services: ServiceBundle, auth: RequestAuth, req: _payloads.DeleteAssetType
) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.asset_type.delete(
        item_id=(auth.tenant_id, req.entity_id),
        auto_commit=False,
    )
    row = await services.change_log.append(
        command=SchemaCommand.DELETE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(
        row.seq, req.entity_id, Outcome.DELETED, row.committed_at
    )
