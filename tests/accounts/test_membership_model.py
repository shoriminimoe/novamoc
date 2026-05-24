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
async def test_membership_same_user_distinct_tenants_allowed_at_schema(
    session: AsyncSession,
) -> None:
    """The table itself is N-to-N — the 1:1 invariant lives in the service."""
    await _enable_foreign_keys(session)
    user = auth_models.User(username="erin", password_hash="hash")  # noqa: S106
    tenant_a = auth_models.Tenant(display_name="Alpha")
    tenant_b = auth_models.Tenant(display_name="Bravo")
    session.add_all([user, tenant_a, tenant_b])
    await session.flush()

    session.add_all(
        [
            auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant_a.id),
            auth_models.UserTenantMembership(user_id=user.id, tenant_id=tenant_b.id),
        ]
    )
    await session.flush()
