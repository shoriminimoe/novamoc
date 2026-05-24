"""Smoke tests for the UserTenantMembership model (ADR-020, M5.4).

The table is not tenant-scoped — these tests opt out of the autouse
``tenant`` fixture so the contextvar isn't set, mirroring the user /
tenant / session model tests.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from novamoc.db.models import _auth as auth_models

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _enable_foreign_keys(session: AsyncSession) -> None:
    """Enable SQLite FK enforcement for the current connection.

    SQLite ships with ``PRAGMA foreign_keys=OFF`` and the aiosqlite
    driver inherits that default; ADR-004 specifies it should be on,
    but production wiring is a separate concern from this milestone.
    """
    await session.execute(text("PRAGMA foreign_keys = ON"))


@pytest.mark.no_tenant
async def test_membership_insert_round_trips(session: AsyncSession) -> None:
    await _enable_foreign_keys(session)
    user = auth_models.User(username="alice", password_hash="hash")  # noqa: S106
    tenant = auth_models.Tenant(display_name="Acme")
    session.add_all([user, tenant])
    await session.flush()

    membership = auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant.id)
    session.add(membership)
    await session.flush()

    assert membership.user_id == user.id
    assert membership.tenant_id == tenant.id


@pytest.mark.no_tenant
async def test_membership_composite_pk_rejects_duplicate_pair(
    session: AsyncSession,
) -> None:
    await _enable_foreign_keys(session)
    user = auth_models.User(username="bob", password_hash="hash")  # noqa: S106
    tenant = auth_models.Tenant(display_name="Beta")
    session.add_all([user, tenant])
    await session.flush()

    session.add(auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()

    session.add(auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.no_tenant
async def test_membership_orphan_user_fk_rejected(session: AsyncSession) -> None:
    await _enable_foreign_keys(session)
    tenant = auth_models.Tenant(display_name="Gamma")
    session.add(tenant)
    await session.flush()

    membership = auth_models.UserTenantMembership(
        user_id=uuid.uuid4(), tenant_id=tenant.id
    )
    session.add(membership)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.no_tenant
async def test_membership_orphan_tenant_fk_rejected(session: AsyncSession) -> None:
    await _enable_foreign_keys(session)
    user = auth_models.User(username="dave", password_hash="hash")  # noqa: S106
    session.add(user)
    await session.flush()

    membership = auth_models.UserTenantMembership(
        user_id=user.id, tenant_id=uuid.uuid4()
    )
    session.add(membership)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.no_tenant
async def test_membership_unique_user_id_rejects_second_tenant(
    session: AsyncSession,
) -> None:
    """``UNIQUE(user_id)`` backstops the v1 1:1 invariant at the DB level."""
    await _enable_foreign_keys(session)
    user = auth_models.User(username="erin", password_hash="hash")  # noqa: S106
    tenant_a = auth_models.Tenant(display_name="Alpha")
    tenant_b = auth_models.Tenant(display_name="Bravo")
    session.add_all([user, tenant_a, tenant_b])
    await session.flush()

    session.add(
        auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant_a.id)
    )
    await session.flush()

    session.add(
        auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant_b.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.no_tenant
async def test_membership_distinct_users_share_a_tenant(
    session: AsyncSession,
) -> None:
    """``UNIQUE(user_id)`` constrains the user side, not the tenant side."""
    await _enable_foreign_keys(session)
    tenant = auth_models.Tenant(display_name="Shared")
    user_a = auth_models.User(username="frank", password_hash="hash")  # noqa: S106
    user_b = auth_models.User(username="grace", password_hash="hash")  # noqa: S106
    session.add_all([tenant, user_a, user_b])
    await session.flush()

    session.add_all(
        [
            auth_models.UserTenantMembership(user_id=user_a.id, tenant_id=tenant.id),
            auth_models.UserTenantMembership(user_id=user_b.id, tenant_id=tenant.id),
        ]
    )
    await session.flush()


@pytest.mark.no_tenant
async def test_membership_cascades_on_user_delete(session: AsyncSession) -> None:
    """``ondelete=CASCADE`` on user FK drops the membership row."""
    await _enable_foreign_keys(session)
    user = auth_models.User(username="harry", password_hash="hash")  # noqa: S106
    tenant = auth_models.Tenant(display_name="Acme")
    session.add_all([user, tenant])
    await session.flush()

    session.add(auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()

    await session.delete(user)
    await session.flush()

    remaining = await session.execute(
        text("SELECT COUNT(*) FROM user_tenant_memberships")
    )
    assert remaining.scalar_one() == 0


@pytest.mark.no_tenant
async def test_membership_restricts_tenant_delete(session: AsyncSession) -> None:
    """``ondelete=RESTRICT`` on tenant FK requires explicit member cleanup."""
    await _enable_foreign_keys(session)
    user = auth_models.User(username="ivy", password_hash="hash")  # noqa: S106
    tenant = auth_models.Tenant(display_name="Locked")
    session.add_all([user, tenant])
    await session.flush()

    session.add(auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()

    await session.delete(tenant)
    with pytest.raises(IntegrityError):
        await session.flush()
