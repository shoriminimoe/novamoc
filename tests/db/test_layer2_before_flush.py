from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import novamoc.db._listeners  # noqa: F401
from novamoc.db._errors import CrossTenantWriteError, UnscopedQueryError
from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.schema._asset_type import AssetType
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_stamps_tenant_id_on_new_instance(session: AsyncSession) -> None:
    obj = AssetType(name="Truck", active=True)
    with use_tenant(DEV_TENANT_ID_A):
        session.add(obj)
        await session.flush()
    assert obj.tenant_id == DEV_TENANT_ID_A


async def test_keeps_explicit_tenant_id_when_matching_context(
    session: AsyncSession,
) -> None:
    obj = AssetType(tenant_id=DEV_TENANT_ID_A, name="Truck", active=True)
    with use_tenant(DEV_TENANT_ID_A):
        session.add(obj)
        await session.flush()
    assert obj.tenant_id == DEV_TENANT_ID_A


@pytest.mark.no_tenant
async def test_raises_when_no_context_and_no_tenant_id(session: AsyncSession) -> None:
    obj = AssetType(name="Truck", active=True)
    session.add(obj)
    with pytest.raises(UnscopedQueryError):
        await session.flush()


async def test_raises_on_cross_tenant_write(session: AsyncSession) -> None:
    obj = AssetType(tenant_id=DEV_TENANT_ID_B, name="Truck", active=True)
    with use_tenant(DEV_TENANT_ID_A):
        session.add(obj)
        with pytest.raises(CrossTenantWriteError):
            await session.flush()
