"""Unit tests for ``resolve_principal_from_session`` (M5.11, ADR-020).

The resolver is the credential-format swap point ADR-017 designed for;
these tests pin its accept/reject behaviour without booting a Litestar
app or any middleware. Each case seeds the registry rows via direct
service calls against the in-memory ``session`` fixture, builds a
session-payload dict, and exercises the resolver.

The auth registry tables (``users``, ``tenants``,
``user_tenant_memberships``) are not tenant-scoped — this module opts
out of the autouse ``tenant`` fixture en bloc.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from novamoc.db.models._auth import Tenant
from novamoc.domain.accounts import (
    Principal,
    RequestAuth,
    TenantResolutionError,
    resolve_principal_from_session,
)
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)
from tests._constants import DEV_TENANT_ID, DEV_USERNAME

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.db.models import _auth as auth_models


pytestmark = pytest.mark.no_tenant


# Production defaults take ~100-300 ms per hash; the weakened parameters
# keep these resolver tests sub-second. The resolver does not verify
# passwords (login does), but the User row needs *some* hash to round-trip.
_FAST = PasswordHasher(time_cost=1, memory_cost_kib=8192, parallelism=1)


async def _seed_admin(
    session: AsyncSession,
    *,
    username: str = DEV_USERNAME,
    disabled_at: datetime | None = None,
    grant_membership: bool = True,
) -> tuple[auth_models.User, auth_models.Tenant]:
    users = UserService(session=session)
    tenants = TenantService(session=session)
    memberships = UserTenantMembershipService(session=session)

    # Pin DEV_TENANT_ID via repository.add: TenantService.create would
    # let advanced_alchemy assign a fresh UUIDv7, but this test needs
    # a deterministic value to read on the resolved RequestAuth.
    tenant = Tenant(id=DEV_TENANT_ID, display_name="Acme")
    await tenants.repository.add(tenant)
    user = await users.create(
        data={
            "username": username,
            "password_hash": _FAST.hash("ignored-by-resolver"),
            "disabled_at": disabled_at,
        },
        auto_commit=False,
    )
    if grant_membership:
        await memberships.create(
            data={"user_id": user.id, "tenant_id": tenant.id},
            auto_commit=False,
        )
    await session.flush()
    return user, tenant


async def test_happy_path_returns_principal_and_auth(session: AsyncSession) -> None:
    user, tenant = await _seed_admin(session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    principal, auth = await resolve_principal_from_session(
        {"user_id": str(user.id), "active_tenant_id": str(tenant.id)},
        users=users,
        memberships=memberships,
    )

    assert principal == Principal(id=str(user.id), username=DEV_USERNAME)
    assert auth == RequestAuth(tenant_id=tenant.id)


async def test_missing_user_id_key_raises(session: AsyncSession) -> None:
    _, tenant = await _seed_admin(session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"active_tenant_id": str(tenant.id)},
            users=users,
            memberships=memberships,
        )


async def test_missing_active_tenant_id_key_raises(session: AsyncSession) -> None:
    user, _ = await _seed_admin(session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"user_id": str(user.id)},
            users=users,
            memberships=memberships,
        )


async def test_empty_payload_raises(session: AsyncSession) -> None:
    """An anonymous request lands with ``scope['session'] == {}``."""
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session({}, users=users, memberships=memberships)


async def test_unknown_user_id_raises(session: AsyncSession) -> None:
    _, tenant = await _seed_admin(session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    unknown_user_id = "01900000-0000-7000-8000-0000000000ff"

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"user_id": unknown_user_id, "active_tenant_id": str(tenant.id)},
            users=users,
            memberships=memberships,
        )


async def test_disabled_user_raises(session: AsyncSession) -> None:
    user, tenant = await _seed_admin(session, disabled_at=datetime.now(tz=UTC))
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"user_id": str(user.id), "active_tenant_id": str(tenant.id)},
            users=users,
            memberships=memberships,
        )


async def test_active_tenant_without_membership_raises(
    session: AsyncSession,
) -> None:
    user, tenant = await _seed_admin(session, grant_membership=False)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"user_id": str(user.id), "active_tenant_id": str(tenant.id)},
            users=users,
            memberships=memberships,
        )


async def test_malformed_uuid_in_payload_raises(session: AsyncSession) -> None:
    user, _ = await _seed_admin(session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            {"user_id": str(user.id), "active_tenant_id": "not-a-uuid"},
            users=users,
            memberships=memberships,
        )
