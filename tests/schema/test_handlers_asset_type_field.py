from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.db.models.schema import FieldDataType
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome
from novamoc.domain.schema import _payloads


_T = "t1"


async def _make_parent(
    session: AsyncSession, services: ServiceBundle, *, active: bool = True
):
    type_id = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": type_id, "name": f"T-{type_id}", "active": active},
        auto_commit=False,
    )
    await session.flush()
    return type_id


async def _make_field(
    session: AsyncSession,
    services: ServiceBundle,
    *,
    parent,
    active: bool = True,
):
    fid = uuid4()
    await services.asset_type_field.create(
        data={
            "tenant_id": _T,
            "id": fid,
            "parent_id": parent,
            "name": "vin",
            "data_type": "text",
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
        _payloads.CreateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_payloads._AssetTypeFieldCreatePayload(
                parent_id=parent,
                name="vin",
                data_type=FieldDataType.TEXT,
            ),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert (
        row is not None
        and row.name == "vin"
        and row.parent_id == parent
        and row.active is True
    )

    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == SchemaCommand.CREATE_ASSET_TYPE_FIELD


async def test_create_with_missing_parent_rejects(services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _payloads.CreateAssetTypeField(
                tenant_id=_T,
                entity_id=uuid4(),
                payload=_payloads._AssetTypeFieldCreatePayload(
                    parent_id=uuid4(),
                    name="vin",
                    data_type=FieldDataType.TEXT,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.PARENT_TYPE_NOT_FOUND


async def test_create_with_deactivated_parent_is_allowed(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services, active=False)
    fid = uuid4()
    out = await dispatch(
        services,
        _payloads.CreateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_payloads._AssetTypeFieldCreatePayload(
                parent_id=parent,
                name="vin",
                data_type=FieldDataType.TEXT,
            ),
        ),
    )
    assert out.outcome is Outcome.CREATED


async def test_create_name_collision(
    session: AsyncSession, services: ServiceBundle
) -> None:
    parent = await _make_parent(session, services)
    await _make_field(session, services, parent=parent)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _payloads.CreateAssetTypeField(
                tenant_id=_T,
                entity_id=uuid4(),
                payload=_payloads._AssetTypeFieldCreatePayload(
                    parent_id=parent,
                    name="vin",
                    data_type=FieldDataType.TEXT,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- activate ---


async def test_activate_when_deactivated(
    session: AsyncSession, services: ServiceBundle
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent, active=False)
    out = await dispatch(
        services,
        _payloads.ActivateAssetTypeField(
            tenant_id=_T, entity_id=fid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.ACTIVATED


async def test_activate_when_already_active_is_noop(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent, active=True)
    out = await dispatch(
        services,
        _payloads.ActivateAssetTypeField(
            tenant_id=_T, entity_id=fid, payload=_payloads._Empty()
        ),
    )
    assert out.outcome is Outcome.NOOP


async def test_activate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _payloads.ActivateAssetTypeField(
                tenant_id=_T, entity_id=uuid4(), payload=_payloads._Empty()
            ),
        )


# --- update / deactivate / clear / delete ---


async def test_update_field_changes_data_type(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _payloads.UpdateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_payloads._AssetTypeFieldUpdatePayload(
                data_type=FieldDataType.NUMBER
            ),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None and row.data_type == "number"


async def test_update_field_no_changes_rejects(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    with pytest.raises(PayloadShapeError):
        await dispatch(
            services,
            _payloads.UpdateAssetTypeField(
                tenant_id=_T,
                entity_id=fid,
                payload=_payloads._AssetTypeFieldUpdatePayload(),
            ),
        )


async def test_update_field_explicit_null_clears_validation(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    """Sending ``validation: null`` writes NULL to the column, distinct from absence."""
    parent = await _make_parent(session, services)
    fid = uuid4()
    await services.asset_type_field.create(
        data={
            "tenant_id": _T,
            "id": fid,
            "parent_id": parent,
            "name": "vin",
            "data_type": "text",
            "validation": {"max_length": 17},
            "active": True,
        },
        auto_commit=False,
    )
    await session.flush()

    # Update name only — validation must remain populated (UNSET is filtered out).
    await dispatch(
        services,
        _payloads.UpdateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_payloads._AssetTypeFieldUpdatePayload(name="vin_number"),
        ),
    )
    await session.flush()
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None and row.validation == {"max_length": 17}

    # Now explicitly clear validation via null.
    await dispatch(
        services,
        _payloads.UpdateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_payloads._AssetTypeFieldUpdatePayload(validation=None),
        ),
    )
    await session.flush()
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert row is not None and row.validation is None


async def test_deactivate_field(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _payloads.DeactivateAssetTypeField(
            tenant_id=_T, entity_id=fid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED


async def test_clear_field_appends_log_row(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _payloads.ClearAssetTypeField(
            tenant_id=_T, entity_id=fid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CLEARED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == SchemaCommand.CLEAR_ASSET_TYPE_FIELD


async def test_delete_field(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        _payloads.DeleteAssetTypeField(
            tenant_id=_T, entity_id=fid, payload=_payloads._Empty()
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid) is None


async def test_field_commands_against_missing_field_raise_not_found(
    services: ServiceBundle,
) -> None:
    eid = uuid4()
    for cmd in (
        _payloads.UpdateAssetTypeField(
            tenant_id=_T,
            entity_id=eid,
            payload=_payloads._AssetTypeFieldUpdatePayload(name="x"),
        ),
        _payloads.ActivateAssetTypeField(
            tenant_id=_T, entity_id=eid, payload=_payloads._Empty()
        ),
        _payloads.DeactivateAssetTypeField(
            tenant_id=_T, entity_id=eid, payload=_payloads._Empty()
        ),
        _payloads.ClearAssetTypeField(
            tenant_id=_T, entity_id=eid, payload=_payloads._Empty()
        ),
        _payloads.DeleteAssetTypeField(
            tenant_id=_T, entity_id=eid, payload=_payloads._Empty()
        ),
    ):
        with pytest.raises(EntityNotFoundError):
            await dispatch(services, cmd)
