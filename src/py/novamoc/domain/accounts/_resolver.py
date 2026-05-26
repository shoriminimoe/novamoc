"""Tenant + principal resolution from the session payload (ADR-020, M5.11).

The swap point ADR-017 designed for. The v1 implementation read a
bearer token off the ``Authorization`` header; v2 reads
``{"user_id", "active_tenant_id"}`` off the request's session payload,
loads the user, confirms membership, and returns the
``(Principal, RequestAuth)`` pair that lands on ``scope["user"]`` and
``scope["auth"]`` respectively.

Five failure paths fold into a single :class:`TenantResolutionError`
so the wire byte-pattern is identical across shapes (analogous to
ADR-020's anti-enumeration login fold): missing session keys, unknown
user, disabled user, membership absent for the active tenant. The
caller renders that error as 401 via the
``TenantResolutionError -> tenant_resolution_error_to_problem_details``
mapper registered in :mod:`novamoc.asgi`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._principal import Principal

if TYPE_CHECKING:
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )


def _parse_uuid(value: Any) -> UUID | None:
    """Coerce a session-payload value to a UUID, returning ``None`` on any failure.

    Session payloads round-trip through JSON, so both UUIDs ride as
    strings. A non-string or malformed value is treated the same as
    "key absent" — the resolver raises the single
    :class:`TenantResolutionError` either way.
    """
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def resolve_principal_from_session(
    session_payload: dict[str, Any],
    *,
    users: UserService,
    memberships: UserTenantMembershipService,
) -> tuple[Principal, RequestAuth]:
    """Resolve the request's principal and active tenant from the session payload.

    Args:
        session_payload: The dict Litestar's SessionMiddleware populates
            on ``scope["session"]``. Expected to carry ``user_id`` and
            ``active_tenant_id`` as UUID strings (login writes them
            this way; see :func:`domain.accounts._handlers.login`).
        users: The registry-side user service, bound to the per-request
            transient session opened by the authentication middleware.
        memberships: The registry-side membership service, same binding.

    Returns:
        ``(Principal, RequestAuth)`` — the principal lands on
        ``scope["user"]``, the auth scope on ``scope["auth"]``.

    Raises:
        TenantResolutionError: Any failure path (missing session keys,
            unknown user, disabled user, membership absent). The single
            error type is the anti-enumeration contract.
    """
    user_id = _parse_uuid(session_payload.get("user_id"))
    tenant_id = _parse_uuid(session_payload.get("active_tenant_id"))
    if user_id is None or tenant_id is None:
        raise TenantResolutionError

    user = await users.get_one_or_none(id=user_id)
    if user is None or user.disabled_at is not None:
        raise TenantResolutionError

    membership = await memberships.get_one_or_none(user_id=user_id, tenant_id=tenant_id)
    if membership is None:
        raise TenantResolutionError

    return (
        Principal(id=str(user.id), username=user.username),
        RequestAuth(tenant_id=tenant_id),
    )
