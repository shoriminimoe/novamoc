"""Service-layer tests for UserTenantMembership (ADR-020, M5.4).

Pins the v1 one-membership-per-user invariant: a second ``create`` for
the same ``user_id`` raises ``UserAlreadyHasTenantError``. The table
itself is N-to-N; only the service enforces 1:1.

Not tenant-scoped, so the autouse ``tenant`` fixture is skipped on every
test in this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from novamoc.db.models._auth import UserTenantMembership
from novamoc.domain.accounts._errors import UserAlreadyHasTenantError
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.db.models import _auth as auth_models


pytestmark = pytest.mark.no_tenant


async def _make_user(session: AsyncSession, username: str) -> auth_models.User:
    svc = UserService(session=session)
    user = await svc.create(
        data={"username": username, "password_hash": "hash"},
        auto_commit=False,
    )
    await session.flush()
    return user


async def _make_tenant(session: AsyncSession, display_name: str) -> auth_models.Tenant:
    svc = TenantService(session=session)
    tenant = await svc.create(
        data={"display_name": display_name},
        auto_commit=False,
    )
    await session.flush()
    return tenant


async def test_create_first_membership_succeeds(session: AsyncSession) -> None:
    user = await _make_user(session, "alice")
    tenant = await _make_tenant(session, "Acme")
    svc = UserTenantMembershipService(session=session)

    membership = await svc.create(
        data={"user_id": user.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()

    assert membership.user_id == user.id
    assert membership.tenant_id == tenant.id


async def test_create_second_membership_for_same_user_raises(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "bob")
    tenant_a = await _make_tenant(session, "Alpha")
    tenant_b = await _make_tenant(session, "Bravo")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": user.id, "tenant_id": tenant_a.id},
        auto_commit=False,
    )
    await session.flush()

    with pytest.raises(UserAlreadyHasTenantError):
        await svc.create(
            data={"user_id": user.id, "tenant_id": tenant_b.id},
            auto_commit=False,
        )


async def test_create_after_delete_succeeds(session: AsyncSession) -> None:
    """The invariant cares about live state, not history."""
    user = await _make_user(session, "carol")
    tenant_a = await _make_tenant(session, "Alpha")
    tenant_b = await _make_tenant(session, "Bravo")
    svc = UserTenantMembershipService(session=session)

    first = await svc.create(
        data={"user_id": user.id, "tenant_id": tenant_a.id},
        auto_commit=False,
    )
    await session.flush()

    await svc.delete(item_id=(first.user_id, first.tenant_id), auto_commit=False)
    await session.flush()

    second = await svc.create(
        data={"user_id": user.id, "tenant_id": tenant_b.id},
        auto_commit=False,
    )
    await session.flush()

    assert second.tenant_id == tenant_b.id


async def test_list_for_user_returns_empty_when_no_membership(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "dave")
    svc = UserTenantMembershipService(session=session)

    assert await svc.list_for_user(user.id) == []


async def test_list_for_user_returns_single_membership(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "erin")
    tenant = await _make_tenant(session, "Alpha")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": user.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()

    rows = await svc.list_for_user(user.id)
    assert [(m.user_id, m.tenant_id) for m in rows] == [(user.id, tenant.id)]


async def test_get_for_user_returns_none_when_no_membership(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "frank")
    svc = UserTenantMembershipService(session=session)

    assert await svc.get_for_user(user.id) is None


async def test_get_for_user_returns_membership(session: AsyncSession) -> None:
    user = await _make_user(session, "grace")
    tenant = await _make_tenant(session, "Alpha")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": user.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()

    found = await svc.get_for_user(user.id)
    assert found is not None
    assert found.tenant_id == tenant.id


async def test_get_by_user_and_tenant_returns_none_when_absent(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "naomi")
    tenant = await _make_tenant(session, "Alpha")
    svc = UserTenantMembershipService(session=session)

    assert await svc.get_by_user_and_tenant(user.id, tenant.id) is None


async def test_get_by_user_and_tenant_returns_existing_membership(
    session: AsyncSession,
) -> None:
    """``bootstrap-admin`` (issue #128) leans on this to detect the
    "user and tenant exist but membership never landed" partial-failure
    case from a prior aborted run."""
    user = await _make_user(session, "oscar")
    tenant = await _make_tenant(session, "Alpha")
    svc = UserTenantMembershipService(session=session)

    created = await svc.create(
        data={"user_id": user.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()

    found = await svc.get_by_user_and_tenant(user.id, tenant.id)
    assert found is not None
    assert (found.user_id, found.tenant_id) == (created.user_id, created.tenant_id)


async def test_get_by_user_and_tenant_distinguishes_users(
    session: AsyncSession,
) -> None:
    """Asymmetric arguments — looking up the *wrong* user against a
    valid tenant must miss, not silently return some other user's row."""
    alice = await _make_user(session, "patty")
    bob = await _make_user(session, "quincy")
    tenant = await _make_tenant(session, "Alpha")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": alice.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()

    assert await svc.get_by_user_and_tenant(bob.id, tenant.id) is None


async def test_string_form_uuid_in_dict_payload_is_extracted(
    session: AsyncSession,
) -> None:
    """``GUID`` admits string UUIDs at the column boundary, so the
    pre-check normalises them rather than silently bypassing the
    invariant."""
    user = await _make_user(session, "hugo")
    tenant_a = await _make_tenant(session, "Alpha")
    tenant_b = await _make_tenant(session, "Bravo")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": str(user.id), "tenant_id": str(tenant_a.id)},
        auto_commit=False,
    )
    await session.flush()

    with pytest.raises(UserAlreadyHasTenantError):
        await svc.create(
            data={"user_id": str(user.id), "tenant_id": str(tenant_b.id)},
            auto_commit=False,
        )


async def test_db_unique_backstops_direct_insert(
    session: AsyncSession,
) -> None:
    """``UNIQUE(user_id)`` rejects a second membership inserted
    directly via the ORM (bypassing the service entirely), proving
    the structural backstop the service docstring promises."""
    user = await _make_user(session, "iris")
    tenant_a = await _make_tenant(session, "Alpha")
    tenant_b = await _make_tenant(session, "Bravo")
    svc = UserTenantMembershipService(session=session)

    await svc.create(
        data={"user_id": user.id, "tenant_id": tenant_a.id},
        auto_commit=False,
    )
    await session.flush()

    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant_b.id))
    with pytest.raises(IntegrityError):
        await session.flush()
