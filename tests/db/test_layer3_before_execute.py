from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, insert, update

import novamoc.db._listeners  # noqa: F401
from novamoc.db._errors import UnscopedQueryError
from novamoc.db._tenant_context import SKIP_TENANT_FILTER, use_tenant
from novamoc.db.models.schema._asset_type import AssetType
from tests._constants import DEV_TENANT_ID_A

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_core_insert_without_tenant_raises(session: AsyncSession) -> None:
    stmt = insert(AssetType).values(
        id="00000000-0000-0000-0000-000000000001", name="X", active=True
    )
    with use_tenant(DEV_TENANT_ID_A), pytest.raises(UnscopedQueryError):
        await session.execute(stmt)


async def test_core_update_without_tenant_predicate_raises(
    session: AsyncSession,
) -> None:
    with use_tenant(DEV_TENANT_ID_A):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = update(AssetType).values(name="Lorry").where(AssetType.name == "Truck")
    with use_tenant(DEV_TENANT_ID_A), pytest.raises(UnscopedQueryError):
        await session.execute(stmt)


async def test_core_delete_without_tenant_predicate_raises(
    session: AsyncSession,
) -> None:
    with use_tenant(DEV_TENANT_ID_A):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = delete(AssetType).where(AssetType.name == "Truck")
    with use_tenant(DEV_TENANT_ID_A), pytest.raises(UnscopedQueryError):
        await session.execute(stmt)


async def test_core_update_with_tenant_predicate_passes(
    session: AsyncSession,
) -> None:
    with use_tenant(DEV_TENANT_ID_A):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = (
        update(AssetType)
        .values(name="Lorry")
        .where(AssetType.tenant_id == DEV_TENANT_ID_A, AssetType.name == "Truck")
    )
    with use_tenant(DEV_TENANT_ID_A):
        await session.execute(stmt)  # no raise


async def test_skip_tenant_filter_disables_layer3(session: AsyncSession) -> None:
    stmt = (
        update(AssetType)
        .values(name="Y")
        .where(AssetType.name == "Z")
        .execution_options(**{SKIP_TENANT_FILTER: True})
    )
    with use_tenant(DEV_TENANT_ID_A):
        await session.execute(stmt)  # no raise even though no tenant_id predicate
