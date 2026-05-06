from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

import novamoc.db._listeners  # noqa: F401
from novamoc.db._errors import UnscopedQueryError
from novamoc.db._tenant_context import SKIP_TENANT_FILTER, use_tenant
from novamoc.db.models.schema._asset_type import AssetType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_two_tenants(session: AsyncSession) -> None:
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    with use_tenant("t-b"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()


async def test_select_under_tenant_returns_only_own_rows(session: AsyncSession) -> None:
    await _seed_two_tenants(session)
    with use_tenant("t-a"):
        result = (await session.execute(select(AssetType))).scalars().all()
    assert {row.tenant_id for row in result} == {"t-a"}


@pytest.mark.no_tenant
async def test_select_without_context_raises(session: AsyncSession) -> None:
    # Seed under explicit contexts so the table is non-empty for the read.
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    # The autouse fixture is opted out (@no_tenant), so the contextvar is
    # None at this point — the SELECT should fail closed.
    with pytest.raises(UnscopedQueryError):
        (await session.execute(select(AssetType))).scalars().all()


async def test_skip_tenant_filter_disables_layer1(session: AsyncSession) -> None:
    await _seed_two_tenants(session)
    # Cross-tenant administrative read.
    result = (
        (
            await session.execute(
                select(AssetType).execution_options(**{SKIP_TENANT_FILTER: True})
            )
        )
        .scalars()
        .all()
    )
    assert {row.tenant_id for row in result} == {"t-a", "t-b"}
