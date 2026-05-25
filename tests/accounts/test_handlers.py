"""Unit tests for the auth handler functions (M5.10, issue #91).

Exercises the module-level ``login`` / ``logout`` / ``me`` functions in
``novamoc.domain.accounts._handlers`` against real account services
backed by an in-memory engine. Anti-enumeration cases fold into one
``LoginFailedError`` per ADR-020 / M5.6.

The handlers' only Litestar touch points are
``request.set_session`` / ``request.clear_session`` and ``request.user`` /
``request.auth``. The session middleware that wires these to the cookie
store lands in M5.11; the unit tests here use a tiny stand-in
:class:`_FakeRequest` to capture session payloads and expose principal /
auth.

The auth registry tables (``users``, ``tenants``, ``user_tenant_memberships``)
are not tenant-scoped, so the test module opts out of the autouse
``tenant`` fixture en bloc with ``pytestmark = pytest.mark.no_tenant``.
"""

# Tests deliberately use hardcoded password literals to exercise the
# argon2id verify path end-to-end.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from msgspec_ext import SecretStr

from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import LoginFailedError
from novamoc.domain.accounts._handlers import login, logout, me
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._payloads import (
    LoginRequest,
    MePrincipal,
    MeResponse,
    MeTenant,
)
from novamoc.domain.accounts._principal import Principal
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.db.models import _auth as auth_models


pytestmark = pytest.mark.no_tenant


# Production defaults take ~100-300 ms per hash; use the same weakened
# parameters as ``tests/accounts/test_password.py`` so login round-trips
# stay sub-second.
_FAST = PasswordHasher(time_cost=1, memory_cost_kib=8192, parallelism=1)


@dataclass
class _FakeRequest:
    """Minimal stand-in for ``litestar.Request`` for handler unit tests.

    Captures :meth:`set_session` payloads and exposes ``user`` / ``auth``
    attributes the real middleware would populate. Only the surface the
    M5.10 handlers actually touch is implemented — adding fields here
    would tie tests to implementation details.
    """

    session_payload: dict[str, Any] | None = None
    cleared: bool = False
    user: Principal | None = None
    auth: RequestAuth | None = None
    session_log: list[dict[str, Any]] = field(default_factory=list)

    def set_session(self, data: dict[str, Any]) -> None:
        self.session_payload = data
        self.session_log.append(data)

    def clear_session(self) -> None:
        self.cleared = True


async def _make_user(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    hasher: PasswordHasher = _FAST,
    disabled_at: datetime | None = None,
) -> auth_models.User:
    svc = UserService(session=session)
    user = await svc.create(
        data={
            "username": username,
            "password_hash": hasher.hash(password),
            "disabled_at": disabled_at,
        },
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


async def _grant_membership(
    session: AsyncSession,
    user: auth_models.User,
    tenant: auth_models.Tenant,
) -> None:
    svc = UserTenantMembershipService(session=session)
    await svc.create(
        data={"user_id": user.id, "tenant_id": tenant.id},
        auto_commit=False,
    )
    await session.flush()


# ----- login ----------------------------------------------------------------


async def test_login_happy_path_sets_session(session: AsyncSession) -> None:
    user = await _make_user(session, "alice", "hunter2")
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)

    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    await login(
        request=request,
        data=LoginRequest(username="alice", password=SecretStr("hunter2")),
        users=users,
        memberships=memberships,
        password_hasher=_FAST,
    )

    assert request.session_payload == {
        "user_id": str(user.id),
        "active_tenant_id": str(tenant.id),
    }


async def test_login_folds_username_before_lookup(session: AsyncSession) -> None:
    """``Admin`` and ``admin`` resolve to the same row (ADR-020)."""
    user = await _make_user(session, "admin", "hunter2")
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)

    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    await login(
        request=request,
        data=LoginRequest(username="Admin", password=SecretStr("hunter2")),
        users=users,
        memberships=memberships,
        password_hasher=_FAST,
    )

    assert request.session_payload == {
        "user_id": str(user.id),
        "active_tenant_id": str(tenant.id),
    }


async def test_login_unknown_user_raises_login_failed(
    session: AsyncSession,
) -> None:
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    with pytest.raises(LoginFailedError):
        await login(
            request=request,
            data=LoginRequest(username="nobody", password=SecretStr("hunter2")),
            users=users,
            memberships=memberships,
            password_hasher=_FAST,
        )
    assert request.session_payload is None


async def test_login_wrong_password_raises_login_failed(
    session: AsyncSession,
) -> None:
    user = await _make_user(session, "alice", "correct-horse")
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)

    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    with pytest.raises(LoginFailedError):
        await login(
            request=request,
            data=LoginRequest(username="alice", password=SecretStr("wrong-password")),
            users=users,
            memberships=memberships,
            password_hasher=_FAST,
        )
    assert request.session_payload is None


async def test_login_disabled_user_raises_login_failed(
    session: AsyncSession,
) -> None:
    user = await _make_user(
        session,
        "alice",
        "hunter2",
        disabled_at=datetime.now(tz=UTC),
    )
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)

    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    with pytest.raises(LoginFailedError):
        await login(
            request=request,
            data=LoginRequest(username="alice", password=SecretStr("hunter2")),
            users=users,
            memberships=memberships,
            password_hasher=_FAST,
        )
    assert request.session_payload is None


async def test_login_zero_memberships_raises_login_failed(
    session: AsyncSession,
) -> None:
    """User exists, password is correct, but has no membership row.

    Folded with the other anti-enumeration cases; the M5.4 N:1 invariant
    means this is the transient zero-membership state, not a steady-state
    multi-membership condition.
    """
    await _make_user(session, "alice", "hunter2")

    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    with pytest.raises(LoginFailedError):
        await login(
            request=request,
            data=LoginRequest(username="alice", password=SecretStr("hunter2")),
            users=users,
            memberships=memberships,
            password_hasher=_FAST,
        )
    assert request.session_payload is None


async def test_login_rehashes_password_when_parameters_rotate(
    session: AsyncSession,
) -> None:
    """Successful login with an out-of-date hash upgrades the stored hash.

    The fixture seeds the user with the weakened ``_FAST`` parameters,
    then the login handler runs with a stronger hasher whose
    :meth:`check_needs_rehash` will return True.
    """
    user = await _make_user(session, "alice", "hunter2", hasher=_FAST)
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)
    original_hash = user.password_hash

    stronger = PasswordHasher(time_cost=2, memory_cost_kib=8192, parallelism=1)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)
    request = _FakeRequest()

    await login(
        request=request,
        data=LoginRequest(username="alice", password=SecretStr("hunter2")),
        users=users,
        memberships=memberships,
        password_hasher=stronger,
    )
    await session.flush()

    reloaded = await users.get(item_id=user.id)
    assert reloaded.password_hash != original_hash
    assert stronger.verify(reloaded.password_hash, "hunter2") is True


# ----- logout ---------------------------------------------------------------


async def test_logout_calls_clear_session() -> None:
    request = _FakeRequest()

    await logout(request=request)

    assert request.cleared is True


# ----- me -------------------------------------------------------------------


async def test_me_returns_user_and_tenant(session: AsyncSession) -> None:
    user = await _make_user(session, "alice", "hunter2")
    tenant = await _make_tenant(session, "Acme")
    await _grant_membership(session, user, tenant)

    tenants = TenantService(session=session)
    request = _FakeRequest(
        user=Principal(id=str(user.id), username="alice"),
        auth=RequestAuth(tenant_id=tenant.id),
    )

    result = await me(request=request, tenants=tenants)

    assert result == MeResponse(
        user=MePrincipal(id=str(user.id), username="alice"),
        tenant=MeTenant(id=str(tenant.id), display_name="Acme"),
    )
