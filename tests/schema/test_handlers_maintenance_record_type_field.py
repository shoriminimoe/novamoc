from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.db.models.schema import FieldDataType
from novamoc.domain.accounts import RequestAuth
from novamoc.domain.schema import _payloads
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema._errors import ConflictError, EntityNotFoundError, ErrorCode
from novamoc.domain.schema._outcomes import Outcome

_T = "t1"
_AUTH = RequestAuth(tenant_id=_T)


async def _make_parent(
    session: AsyncSession,
    services: ServiceBundle,
    *,
    active: bool = True,
):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": f"T-{eid}", "active": active},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_field(
    session: AsyncSession,
    services: ServiceBundle,
    *,
    parent,
    active: bool = True,
):
    fid = uuid4()
    await services.maintenance_record_type_field.create(
        data={
            "tenant_id": _T,
            "id": fid,
            "parent_id": parent,
            "name": "mileage",
            "data_type": "number",
            "validation": None,
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return fid


# --- create ---


async def test_create(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = uuid4()
    out = await dispatch(
        services,
        _AUTH,
        _payloads.CreateMaintenanceRecordTypeField(
            entity_id=fid,
            payload=_payloads._MaintenanceRecordTypeFieldCreatePayload(
                parent_id=parent,
                name="mileage",
                data_type=FieldDataType.NUMBER,
            ),
        ),
    )
    assert out.outcome is Outcome.CREATED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE_FIELD


async def test_create_with_missing_parent_rejects(services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.CreateMaintenanceRecordTypeField(
                entity_id=uuid4(),
                payload=_payloads._MaintenanceRecordTypeFieldCreatePayload(
                    parent_id=uuid4(),
                    name="mileage",
                    data_type=FieldDataType.NUMBER,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.PARENT_TYPE_NOT_FOUND


# --- activate ---


async def test_activate_when_deactivated(
    session: AsyncSession, services: ServiceBundle
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent, active=False)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ActivateMaintenanceRecordTypeField(
            entity_id=fid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.ACTIVATED


async def test_activate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.ActivateMaintenanceRecordTypeField(
                entity_id=uuid4(),
                payload=_payloads._Empty(),
            ),
        )


# --- update / deactivate / clear / delete ---


async def test_update_changes_data_type(
    session: AsyncSession, services: ServiceBundle
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.UpdateMaintenanceRecordTypeField(
            entity_id=fid,
            payload=_payloads._MaintenanceRecordTypeFieldUpdatePayload(
                data_type=FieldDataType.TEXT
            ),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED


async def test_deactivate(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeactivateMaintenanceRecordTypeField(
            entity_id=fid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.DEACTIVATED


async def test_clear_field_appends_log_row(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ClearMaintenanceRecordTypeField(
            entity_id=fid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CLEARED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == SchemaCommand.CLEAR_MAINTENANCE_RECORD_TYPE_FIELD


async def test_delete_field(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeleteMaintenanceRecordTypeField(
            entity_id=fid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert (
        await services.maintenance_record_type_field.get_one_or_none(
            tenant_id=_T, id=fid
        )
        is None
    )
