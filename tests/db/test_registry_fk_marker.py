"""Pin the ``info={"registry_fk": True}`` opt-out on the
tenant-scoping listeners.

The membership table carries a ``tenant_id`` column that points at the
``tenants`` registry, not at the row's tenant scope. The listeners'
column-presence heuristic in ``db/_listeners.py`` honors the marker by
treating such tables as non-tenant-scoped across all three layers.
These tests exercise each layer directly so a future refactor that
re-derives the column check locally cannot regress the opt-out
silently.

The membership table is the canonical (and currently only) caller of
the marker; using it here rather than a synthetic fixture means the
tests pin the real behavior callers depend on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, insert, select, update

import novamoc.db._listeners  # noqa: F401
from novamoc.db.models._auth import Tenant, User, UserTenantMembership

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.no_tenant


async def _make_pair(session: AsyncSession) -> tuple[User, Tenant]:
    user = User(username="anna", password_hash="hash")  # noqa: S106
    tenant = Tenant(display_name="Acme")
    session.add_all([user, tenant])
    await session.flush()
    return user, tenant


async def test_layer1_select_without_tenant_context_does_not_raise(
    session: AsyncSession,
) -> None:
    """Layer 1 (``do_orm_execute``) must skip injection when the table
    opts out, otherwise SELECTs without a tenant context would
    fail-closed on a non-scoped table."""
    (await session.execute(select(UserTenantMembership))).scalars().all()


async def test_layer2_orm_insert_without_tenant_context_does_not_raise(
    session: AsyncSession,
) -> None:
    """Layer 2 (``before_flush``) must skip stamping when the table
    opts out, otherwise it would either overwrite the explicit FK
    value or raise on a missing contextvar."""
    user, tenant = await _make_pair(session)
    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()


async def test_layer3_core_insert_without_tenant_predicate_passes(
    session: AsyncSession,
) -> None:
    """Layer 3 (``before_execute``) must skip the unscoped-DML check
    when the target table opts out."""
    user, tenant = await _make_pair(session)
    stmt = insert(UserTenantMembership).values(user_id=user.id, tenant_id=tenant.id)
    await session.execute(stmt)  # no raise


async def test_layer3_core_update_without_tenant_predicate_passes(
    session: AsyncSession,
) -> None:
    user, tenant = await _make_pair(session)
    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()

    other = Tenant(display_name="Bravo")
    session.add(other)
    await session.flush()

    stmt = (
        update(UserTenantMembership)
        .where(UserTenantMembership.user_id == user.id)
        .values(tenant_id=other.id)
    )
    await session.execute(stmt)  # no raise


async def test_layer3_core_delete_without_tenant_predicate_passes(
    session: AsyncSession,
) -> None:
    user, tenant = await _make_pair(session)
    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()

    stmt = delete(UserTenantMembership).where(UserTenantMembership.user_id == user.id)
    await session.execute(stmt)  # no raise
