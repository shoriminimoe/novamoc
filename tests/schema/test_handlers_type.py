"""Handler-level tests for ``asset_type`` and ``maintenance_record_type``.

Both entity kinds share the same six-verb command surface (create,
activate, update, deactivate, delete, plus the no-op outcomes) backed
by the same handler shape over different services. Parametrising the
test bodies across a :class:`TypeSpec` for each kind covers the
matrix in one file; the alternative — two near-identical files —
duplicates ~250 LOC.

``TypeSpec`` captures the per-entity differences: the service attr
on the ``ServiceBundle``, the canonical seed-row name, the
``SchemaCommand`` enum value the change log should record, and the
payload classes for each verb.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from novamoc.db.models import schema as schema_models
from novamoc.domain._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.accounts import RequestAuth
from novamoc.domain.schema import _payloads
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema._outcomes import Outcome
from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.schema._bundle import ServiceBundle

_T = DEV_TENANT_ID
_AUTH = RequestAuth(tenant_id=_T)


@dataclass(frozen=True)
class TypeSpec:
    id: str
    service_attr: str
    sample_name: str
    rename_to: str
    create_cmd: type
    activate_cmd: type
    update_cmd: type
    deactivate_cmd: type
    delete_cmd: type
    create_payload_cls: type
    update_payload_cls: type
    schema_command_create: SchemaCommand


ASSET_TYPE = TypeSpec(
    id="asset_type",
    service_attr="asset_type",
    sample_name="Truck",
    rename_to="Lorry",
    create_cmd=_payloads.CreateAssetType,
    activate_cmd=_payloads.ActivateAssetType,
    update_cmd=_payloads.UpdateAssetType,
    deactivate_cmd=_payloads.DeactivateAssetType,
    delete_cmd=_payloads.DeleteAssetType,
    create_payload_cls=_payloads._AssetTypeCreatePayload,
    update_payload_cls=_payloads._AssetTypeUpdatePayload,
    schema_command_create=SchemaCommand.CREATE_ASSET_TYPE,
)

MR_TYPE = TypeSpec(
    id="maintenance_record_type",
    service_attr="maintenance_record_type",
    sample_name="Service",
    rename_to="Oil Change",
    create_cmd=_payloads.CreateMaintenanceRecordType,
    activate_cmd=_payloads.ActivateMaintenanceRecordType,
    update_cmd=_payloads.UpdateMaintenanceRecordType,
    deactivate_cmd=_payloads.DeactivateMaintenanceRecordType,
    delete_cmd=_payloads.DeleteMaintenanceRecordType,
    create_payload_cls=_payloads._MaintenanceRecordTypeCreatePayload,
    update_payload_cls=_payloads._MaintenanceRecordTypeUpdatePayload,
    schema_command_create=SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE,
)

_SPECS = pytest.mark.parametrize("spec", [ASSET_TYPE, MR_TYPE], ids=lambda s: s.id)


def _service(services: ServiceBundle, spec: TypeSpec) -> Any:
    return getattr(services, spec.service_attr)


async def _make(
    session: AsyncSession,
    services: ServiceBundle,
    spec: TypeSpec,
    *,
    active: bool,
) -> Any:
    eid = uuid4()
    await _service(services, spec).create(
        data={
            "tenant_id": _T,
            "id": eid,
            "name": spec.sample_name,
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return eid


# --- create ---


@_SPECS
async def test_create(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = uuid4()
    out = await dispatch(
        services,
        _AUTH,
        spec.create_cmd(
            entity_id=eid,
            payload=spec.create_payload_cls(name=spec.sample_name),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    assert out.entity_id == eid
    assert out.schema_version > 0
    row = await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.name == spec.sample_name
    assert row.active is True

    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert [r.command for r in log] == [spec.schema_command_create]


@_SPECS
async def test_create_name_collision(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    await _make(session, services, spec, active=True)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.create_cmd(
                entity_id=uuid4(),
                payload=spec.create_payload_cls(name=spec.sample_name),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


@_SPECS
async def test_create_id_collision(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.create_cmd(
                entity_id=eid,
                payload=spec.create_payload_cls(name=spec.rename_to),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- activate ---


@_SPECS
async def test_activate_when_deactivated(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=False)
    out = await dispatch(
        services,
        _AUTH,
        spec.activate_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.ACTIVATED
    row = await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.active is True


@_SPECS
async def test_activate_when_already_active_is_noop(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    out = await dispatch(
        services,
        _AUTH,
        spec.activate_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.NOOP


@_SPECS
async def test_activate_missing_raises_not_found(
    services: ServiceBundle, spec: TypeSpec
) -> None:
    with pytest.raises(EntityNotFoundError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.activate_cmd(entity_id=uuid4(), payload=_payloads._Empty()),
        )
    assert exc_info.value.code is ErrorCode.ENTITY_NOT_FOUND


# --- update ---


@_SPECS
async def test_update_changes_name(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    out = await dispatch(
        services,
        _AUTH,
        spec.update_cmd(
            entity_id=eid,
            payload=spec.update_payload_cls(name=spec.rename_to),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.name == spec.rename_to


@_SPECS
async def test_update_when_deactivated_is_allowed(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=False)
    out = await dispatch(
        services,
        _AUTH,
        spec.update_cmd(
            entity_id=eid,
            payload=spec.update_payload_cls(name=spec.rename_to),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.name == spec.rename_to
    assert row.active is False


@_SPECS
async def test_update_missing_raises_not_found(
    services: ServiceBundle, spec: TypeSpec
) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            spec.update_cmd(
                entity_id=uuid4(),
                payload=spec.update_payload_cls(name="X"),
            ),
        )


@_SPECS
async def test_update_no_changes_rejects(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    with pytest.raises(PayloadShapeError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.update_cmd(entity_id=eid, payload=spec.update_payload_cls()),
        )
    assert exc_info.value.code is ErrorCode.PAYLOAD_NO_CHANGES


# --- deactivate ---


@_SPECS
async def test_deactivate_active(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    out = await dispatch(
        services,
        _AUTH,
        spec.deactivate_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED
    row = await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.active is False


@_SPECS
async def test_deactivate_deactivated_is_noop(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=False)
    out = await dispatch(
        services,
        _AUTH,
        spec.deactivate_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.NOOP


@_SPECS
async def test_deactivate_missing_raises_not_found(
    services: ServiceBundle, spec: TypeSpec
) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            spec.deactivate_cmd(entity_id=uuid4(), payload=_payloads._Empty()),
        )


# --- delete ---


@_SPECS
async def test_delete_removes_row(
    session: AsyncSession, services: ServiceBundle, spec: TypeSpec
) -> None:
    eid = await _make(session, services, spec, active=True)
    out = await dispatch(
        services,
        _AUTH,
        spec.delete_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await _service(services, spec).get_one_or_none(tenant_id=_T, id=eid) is None


@_SPECS
async def test_delete_missing_raises_not_found(
    services: ServiceBundle, spec: TypeSpec
) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            spec.delete_cmd(entity_id=uuid4(), payload=_payloads._Empty()),
        )
