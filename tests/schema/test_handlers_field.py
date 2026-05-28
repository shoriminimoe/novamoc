"""Handler-level tests for ``asset_type_field`` and ``maintenance_record_type_field``.

Both field-on-type entity kinds share the seven-verb command surface
(create / activate / update / deactivate / clear / delete plus the
no-op outcomes) with identical handler shape. Parametrising the test
bodies across a :class:`FieldSpec` for each kind covers the matrix in
one file.

``FieldSpec`` captures the per-entity differences: the parent-type
service attr (for the FK seed row), the field service attr on the
``ServiceBundle``, sample field/data values, the ``SchemaCommand``
enum values, and the payload classes for each verb.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from novamoc.db.models import schema as schema_models
from novamoc.db.models.schema import FieldDataType
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
class FieldSpec:
    id: str
    parent_service_attr: str
    field_service_attr: str
    sample_name: str
    sample_data_type: FieldDataType
    other_data_type: FieldDataType
    create_cmd: type
    activate_cmd: type
    update_cmd: type
    deactivate_cmd: type
    clear_cmd: type
    delete_cmd: type
    create_payload_cls: type
    update_payload_cls: type
    schema_command_create: SchemaCommand
    schema_command_clear: SchemaCommand


ASSET_FIELD = FieldSpec(
    id="asset_type_field",
    parent_service_attr="asset_type",
    field_service_attr="asset_type_field",
    sample_name="vin",
    sample_data_type=FieldDataType.TEXT,
    other_data_type=FieldDataType.NUMBER,
    create_cmd=_payloads.CreateAssetTypeField,
    activate_cmd=_payloads.ActivateAssetTypeField,
    update_cmd=_payloads.UpdateAssetTypeField,
    deactivate_cmd=_payloads.DeactivateAssetTypeField,
    clear_cmd=_payloads.ClearAssetTypeField,
    delete_cmd=_payloads.DeleteAssetTypeField,
    create_payload_cls=_payloads._AssetTypeFieldCreatePayload,
    update_payload_cls=_payloads._AssetTypeFieldUpdatePayload,
    schema_command_create=SchemaCommand.CREATE_ASSET_TYPE_FIELD,
    schema_command_clear=SchemaCommand.CLEAR_ASSET_TYPE_FIELD,
)

MR_FIELD = FieldSpec(
    id="maintenance_record_type_field",
    parent_service_attr="maintenance_record_type",
    field_service_attr="maintenance_record_type_field",
    sample_name="mileage",
    sample_data_type=FieldDataType.NUMBER,
    other_data_type=FieldDataType.TEXT,
    create_cmd=_payloads.CreateMaintenanceRecordTypeField,
    activate_cmd=_payloads.ActivateMaintenanceRecordTypeField,
    update_cmd=_payloads.UpdateMaintenanceRecordTypeField,
    deactivate_cmd=_payloads.DeactivateMaintenanceRecordTypeField,
    clear_cmd=_payloads.ClearMaintenanceRecordTypeField,
    delete_cmd=_payloads.DeleteMaintenanceRecordTypeField,
    create_payload_cls=_payloads._MaintenanceRecordTypeFieldCreatePayload,
    update_payload_cls=_payloads._MaintenanceRecordTypeFieldUpdatePayload,
    schema_command_create=SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE_FIELD,
    schema_command_clear=SchemaCommand.CLEAR_MAINTENANCE_RECORD_TYPE_FIELD,
)

_SPECS = pytest.mark.parametrize("spec", [ASSET_FIELD, MR_FIELD], ids=lambda s: s.id)


def _field_service(services: ServiceBundle, spec: FieldSpec) -> Any:
    return getattr(services, spec.field_service_attr)


def _parent_service(services: ServiceBundle, spec: FieldSpec) -> Any:
    return getattr(services, spec.parent_service_attr)


async def _make_parent(
    session: AsyncSession,
    services: ServiceBundle,
    spec: FieldSpec,
    *,
    active: bool = True,
) -> Any:
    type_id = uuid4()
    await _parent_service(services, spec).create(
        data={
            "tenant_id": _T,
            "id": type_id,
            "name": f"T-{type_id}",
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return type_id


async def _make_field(
    session: AsyncSession,
    services: ServiceBundle,
    spec: FieldSpec,
    *,
    parent: Any,
    active: bool = True,
) -> Any:
    fid = uuid4()
    await _field_service(services, spec).create(
        data={
            "tenant_id": _T,
            "id": fid,
            "parent_id": parent,
            "name": spec.sample_name,
            "data_type": spec.sample_data_type.value,
            "validation": None,
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return fid


# --- create ---


@_SPECS
async def test_create(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = uuid4()
    out = await dispatch(
        services,
        _AUTH,
        spec.create_cmd(
            entity_id=fid,
            payload=spec.create_payload_cls(
                parent_id=parent,
                name=spec.sample_name,
                data_type=spec.sample_data_type,
            ),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    row = await _field_service(services, spec).get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None
    assert row.name == spec.sample_name
    assert row.parent_id == parent
    assert row.active is True

    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == spec.schema_command_create


@_SPECS
async def test_create_with_missing_parent_rejects(
    services: ServiceBundle, spec: FieldSpec
) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.create_cmd(
                entity_id=uuid4(),
                payload=spec.create_payload_cls(
                    parent_id=uuid4(),
                    name=spec.sample_name,
                    data_type=spec.sample_data_type,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.PARENT_TYPE_NOT_FOUND


@_SPECS
async def test_create_with_deactivated_parent_is_allowed(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec, active=False)
    fid = uuid4()
    out = await dispatch(
        services,
        _AUTH,
        spec.create_cmd(
            entity_id=fid,
            payload=spec.create_payload_cls(
                parent_id=parent,
                name=spec.sample_name,
                data_type=spec.sample_data_type,
            ),
        ),
    )
    assert out.outcome is Outcome.CREATED


@_SPECS
async def test_create_name_collision(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    await _make_field(session, services, spec, parent=parent)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            spec.create_cmd(
                entity_id=uuid4(),
                payload=spec.create_payload_cls(
                    parent_id=parent,
                    name=spec.sample_name,
                    data_type=spec.sample_data_type,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- activate ---


@_SPECS
async def test_activate_when_deactivated(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent, active=False)
    out = await dispatch(
        services,
        _AUTH,
        spec.activate_cmd(entity_id=fid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.ACTIVATED


@_SPECS
async def test_activate_when_already_active_is_noop(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent, active=True)
    out = await dispatch(
        services,
        _AUTH,
        spec.activate_cmd(entity_id=fid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.NOOP


@_SPECS
async def test_activate_missing_raises_not_found(
    services: ServiceBundle, spec: FieldSpec
) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            spec.activate_cmd(entity_id=uuid4(), payload=_payloads._Empty()),
        )


# --- update / deactivate / clear / delete ---


@_SPECS
async def test_update_changes_data_type(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        spec.update_cmd(
            entity_id=fid,
            payload=spec.update_payload_cls(data_type=spec.other_data_type),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await _field_service(services, spec).get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None
    assert row.data_type == spec.other_data_type.value


@_SPECS
async def test_update_no_changes_rejects(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent)
    with pytest.raises(PayloadShapeError):
        await dispatch(
            services,
            _AUTH,
            spec.update_cmd(entity_id=fid, payload=spec.update_payload_cls()),
        )


@_SPECS
async def test_update_explicit_null_clears_validation(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    """Sending ``validation: null`` writes NULL to the column, distinct from absence."""
    parent = await _make_parent(session, services, spec)
    fid = uuid4()
    await _field_service(services, spec).create(
        data={
            "tenant_id": _T,
            "id": fid,
            "parent_id": parent,
            "name": spec.sample_name,
            "data_type": spec.sample_data_type.value,
            "validation": {"max_length": 17},
            "active": True,
        },
        auto_commit=False,
    )
    await session.flush()

    # Update name only — validation must remain populated (UNSET is filtered out).
    await dispatch(
        services,
        _AUTH,
        spec.update_cmd(
            entity_id=fid,
            payload=spec.update_payload_cls(name=f"{spec.sample_name}_renamed"),
        ),
    )
    await session.flush()
    row = await _field_service(services, spec).get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None
    assert row.validation == {"max_length": 17}

    # Now explicitly clear validation via null.
    await dispatch(
        services,
        _AUTH,
        spec.update_cmd(
            entity_id=fid,
            payload=spec.update_payload_cls(validation=None),
        ),
    )
    await session.flush()
    row = await _field_service(services, spec).get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None
    assert row.validation is None


@_SPECS
async def test_deactivate(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        spec.deactivate_cmd(entity_id=fid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED


@_SPECS
async def test_clear_field_appends_log_row(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        spec.clear_cmd(entity_id=fid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.CLEARED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == spec.schema_command_clear


@_SPECS
async def test_delete_field(
    session: AsyncSession, services: ServiceBundle, spec: FieldSpec
) -> None:
    parent = await _make_parent(session, services, spec)
    fid = await _make_field(session, services, spec, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        spec.delete_cmd(entity_id=fid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert (
        await _field_service(services, spec).get_one_or_none(tenant_id=_T, id=fid)
        is None
    )


@_SPECS
async def test_field_commands_against_missing_field_raise_not_found(
    services: ServiceBundle, spec: FieldSpec
) -> None:
    eid = uuid4()
    commands = (
        spec.update_cmd(
            entity_id=eid,
            payload=spec.update_payload_cls(name="x"),
        ),
        spec.activate_cmd(entity_id=eid, payload=_payloads._Empty()),
        spec.deactivate_cmd(entity_id=eid, payload=_payloads._Empty()),
        spec.clear_cmd(entity_id=eid, payload=_payloads._Empty()),
        spec.delete_cmd(entity_id=eid, payload=_payloads._Empty()),
    )
    for cmd in commands:
        with pytest.raises(EntityNotFoundError):
            await dispatch(services, _AUTH, cmd)
