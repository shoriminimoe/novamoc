from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.domain.accounts import RequestAuth
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
from tests.data.scenarios import ACTIVE_TRUCK, DEACTIVATED_TRUCK


_T = "t1"
_AUTH = RequestAuth(tenant_id=_T)


async def _make_active_truck(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Truck", "active": True},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_deactivated_truck(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Truck", "active": False},
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
        _payloads.CreateAssetType(
            entity_id=eid,
            payload=_payloads._AssetTypeCreatePayload(name="Truck"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    assert out.entity_id == eid
    assert out.schema_version > 0
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.name == "Truck" and row.active is True

    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert [r.command for r in log] == [SchemaCommand.CREATE_ASSET_TYPE]


async def test_create_name_collision(seed, services: ServiceBundle) -> None:
    await seed(ACTIVE_TRUCK)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.CreateAssetType(
                entity_id=uuid4(),
                payload=_payloads._AssetTypeCreatePayload(name="Truck"),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


async def test_create_id_collision(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active_truck(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.CreateAssetType(
                entity_id=eid,
                payload=_payloads._AssetTypeCreatePayload(name="Lorry"),
            ),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- activate ---


async def test_activate_when_deactivated(
    session: AsyncSession, seed, services: ServiceBundle
) -> None:
    ids = await seed(DEACTIVATED_TRUCK)
    eid = ids["asset_type"]["Truck"]
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ActivateAssetType(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.ACTIVATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.active is True


async def test_activate_when_already_active_is_noop(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.ActivateAssetType(entity_id=eid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.NOOP


async def test_activate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.ActivateAssetType(entity_id=uuid4(), payload=_payloads._Empty()),
        )
    assert exc_info.value.code is ErrorCode.ENTITY_NOT_FOUND


# --- update ---


async def test_update_changes_name(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.UpdateAssetType(
            entity_id=eid,
            payload=_payloads._AssetTypeUpdatePayload(name="Lorry"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.name == "Lorry"


async def test_update_when_deactivated_is_allowed(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_deactivated_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.UpdateAssetType(
            entity_id=eid,
            payload=_payloads._AssetTypeUpdatePayload(name="Lorry"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.name == "Lorry" and row.active is False


async def test_update_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.UpdateAssetType(
                entity_id=uuid4(),
                payload=_payloads._AssetTypeUpdatePayload(name="X"),
            ),
        )


async def test_update_no_changes_rejects(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active_truck(session, services)
    with pytest.raises(PayloadShapeError) as exc_info:
        await dispatch(
            services,
            _AUTH,
            _payloads.UpdateAssetType(
                entity_id=eid, payload=_payloads._AssetTypeUpdatePayload()
            ),
        )
    assert exc_info.value.code is ErrorCode.PAYLOAD_NO_CHANGES


# --- deactivate ---


async def test_deactivate_active(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeactivateAssetType(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.active is False


async def test_deactivate_deactivated_is_noop(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_deactivated_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeactivateAssetType(entity_id=eid, payload=_payloads._Empty()),
    )
    assert out.outcome is Outcome.NOOP


async def test_deactivate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.DeactivateAssetType(
                entity_id=uuid4(), payload=_payloads._Empty()
            ),
        )


# --- delete ---


async def test_delete_removes_row(
    session: AsyncSession, services: ServiceBundle
) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services,
        _AUTH,
        _payloads.DeleteAssetType(entity_id=eid, payload=_payloads._Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.asset_type.get_one_or_none(tenant_id=_T, id=eid) is None


async def test_delete_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            _AUTH,
            _payloads.DeleteAssetType(entity_id=uuid4(), payload=_payloads._Empty()),
        )
