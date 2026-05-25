"""Module-level handler functions for the ``/auth`` routes (M5.10, #91).

The :class:`AuthController` in :mod:`novamoc.domain.accounts.controllers._auth`
is a thin wrapper that resolves DI and forwards to these functions; the
business logic lives here so the handlers stay individually unit-testable
against the in-memory engine fixtures.

Anti-enumeration: every failure path in :func:`login` (unknown user,
wrong password, disabled user, zero memberships) raises the same
:class:`LoginFailedError` so the wire byte-pattern is identical across
shapes (ADR-020).

The session middleware that gives ``request.set_session`` /
``request.clear_session`` their teeth lands in M5.11; the handlers here
are written against the Litestar surface and treat the middleware mount
as a separate concern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from novamoc.domain.accounts._errors import LoginFailedError
from novamoc.domain.accounts._payloads import (
    MePrincipal,
    MeResponse,
    MeTenant,
)

if TYPE_CHECKING:
    from novamoc.domain.accounts._auth import RequestAuth
    from novamoc.domain.accounts._password import PasswordHasher
    from novamoc.domain.accounts._payloads import LoginRequest
    from novamoc.domain.accounts._principal import Principal
    from novamoc.domain.accounts._services import (
        TenantService,
        UserService,
        UserTenantMembershipService,
    )


class _LoginRequest(Protocol):
    """Surface of :class:`litestar.Request` the login handler touches."""

    def set_session(self, data: dict[str, Any], /) -> None: ...


class _LogoutRequest(Protocol):
    """Surface of :class:`litestar.Request` the logout handler touches."""

    def clear_session(self) -> None: ...


class _MeRequest(Protocol):
    """Surface of :class:`litestar.Request` the me handler reads."""

    @property
    def user(self) -> Principal: ...

    @property
    def auth(self) -> RequestAuth: ...


async def login(
    *,
    request: _LoginRequest,
    data: LoginRequest,
    users: UserService,
    memberships: UserTenantMembershipService,
    password_hasher: PasswordHasher,
) -> None:
    """Authenticate the request and seed a session.

    Folds every credential-rejection path into a single
    :class:`LoginFailedError`: unknown user, wrong password, disabled
    user, and the transient zero-membership case all share one wire
    body (ADR-020). On success the handler writes the session payload
    via :meth:`Request.set_session` — the session middleware (M5.11)
    serializes it and emits the ``Set-Cookie`` header.

    A successful verify against an out-of-date hash triggers a free
    upgrade: the user's ``password_hash`` is rewritten with the current
    cost parameters so cost rotations propagate as users log in.

    Raises:
        LoginFailedError: any credential-rejection path.
    """
    user = await users.get_by_username(data.username)
    if user is None or user.disabled_at is not None:
        raise LoginFailedError

    plaintext = data.password.get_secret_value()
    if not password_hasher.verify(user.password_hash, plaintext):
        raise LoginFailedError

    membership = await memberships.get_for_user(user.id)
    if membership is None:
        raise LoginFailedError

    if password_hasher.check_needs_rehash(user.password_hash):
        await users.update(
            data={"password_hash": password_hasher.hash(plaintext)},
            item_id=user.id,
            auto_commit=False,
        )

    request.set_session(
        {
            "user_id": str(user.id),
            "active_tenant_id": str(membership.tenant_id),
        }
    )


async def logout(*, request: _LogoutRequest) -> None:
    """Clear the session.

    The session middleware (M5.11) emits the cookie-clearing
    ``Set-Cookie`` header and deletes the backend row.
    """
    request.clear_session()


async def me(*, request: _MeRequest, tenants: TenantService) -> MeResponse:
    """Return the active user / tenant pair for the current session.

    Reads :attr:`Request.user` (the :class:`Principal`) and
    :attr:`Request.auth` (the :class:`RequestAuth` carrying the active
    tenant id), then loads the tenant row to surface its ``display_name``.
    """
    principal = request.user
    auth = request.auth
    tenant = await tenants.get(item_id=auth.tenant_id)
    return MeResponse(
        user=MePrincipal(id=principal.id, username=principal.username),
        tenant=MeTenant(id=str(tenant.id), display_name=tenant.display_name),
    )
