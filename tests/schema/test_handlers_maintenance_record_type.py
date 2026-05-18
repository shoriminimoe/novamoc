from typing import TYPE_CHECKING
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


async def _make_active(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Service", "active": True},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_deactivated(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Service", "active": False},
        auto_commit=False,
    )
    await session.flush()
    return eid


# --- create ---


async def test_create(session: AsyncSession, services: ServiceBundle) -> None:
    eid = uuid4()
    out = await dispatch(
        services,
        _AUTH,
        _payloads.CreateMaintenanceRecordType(
            entity_id=eid,
            payload=_payloads._MaintenanceRecordTypeCreatePayload(name="Service"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert [r.command for r in log] == [SchemaCommand.CREATE_MAINTENANCE_RECORD_TYPE]


async def test_create_name_collision(
    session: AsyncSession, services: ServiceBundle
) -> None:
    await _make_active(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.CreateMaintenanceRecordType(
                entity_id=uuid4(),
                payload=_payloads._MaintenanceRecordTypeCreatePayload(name="Service"),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- activate ---


async def test_activate_when_deactivated(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_deactivated(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ActivateMaintenanceRecordType(
            entity_id=eid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.ACTIVATED


async def test_activate_when_already_active_is_noop(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ActivateMaintenanceRecordType(
            entity_id=eid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.NOOP


async def test_activate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.ActivateMaintenanceRecordType(
                entity_id=uuid4(), payload=_payloads._Empty()
            ),
        )


# --- update ---


async def test_update_changes_name(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.UpdateMaintenanceRecordType(
            entity_id=eid,
            payload=_payloads._MaintenanceRecordTypeUpdatePayload(name="Oil Change"),
        ),
    )
    assert out.outcome is Outcome.UPDATED


async def test_update_when_deactivated_is_allowed(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    eid = await _make_deactivated(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.UpdateMaintenanceRecordType(
            entity_id=eid,
            payload=_payloads._MaintenanceRecordTypeUpdatePayload(name="Oil Change"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.maintenance_record_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None
    assert row.name == "Oil Change"
    assert row.active is False


async def test_update_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.UpdateMaintenanceRecordType(
                entity_id=uuid4(),
                payload=_payloads._MaintenanceRecordTypeUpdatePayload(name="X"),
            ),
        )


async def test_update_no_changes_rejects(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    eid = await _make_active(session, services)
    with pytest.raises(PayloadShapeError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.UpdateMaintenanceRecordType(
                entity_id=eid,
                payload=_payloads._MaintenanceRecordTypeUpdatePayload(),
            ),
        )
    assert exc_info.value.code is ErrorCode.PAYLOAD_NO_CHANGES


# --- deactivate / delete ---


async def test_deactivate_active(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeactivateMaintenanceRecordType(
            entity_id=eid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.DEACTIVATED


async def test_delete_removes_row(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeleteMaintenanceRecordType(
            entity_id=eid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert (
        await services.maintenance_record_type.get_one_or_none(tenant_id=_T, id=eid)
        is None
    )
