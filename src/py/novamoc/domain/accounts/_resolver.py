"""Tenant resolution from the request envelope.

v1: read the ``Authorization`` header, expect a ``Bearer <token>`` value,
match the token against a single hardcoded constant. On match return
``RequestAuth(tenant_id="t1")``; on any failure raise
``TenantResolutionError``.

This module is the swap point. The v2 resolver will look up the bearer
token in a tenant table (or external IdP) and build a richer auth
object; the middleware and DI layers do not change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.domain.accounts._errors import TenantResolutionError

if TYPE_CHECKING:
    from litestar.datastructures import Headers

# Development-only credential. Anyone with checkout access can read it; that is
# the trust model for the dev period (ADR-017). Replaced by a real per-tenant
# token registry — see issue #19.
_TENANT_T1_DEV_TOKEN = "t1-dev-token"  # noqa: S105 — dev-only credential, see issue #19
_TENANT_T1 = "t1"

_BEARER_PREFIX = "Bearer "


def resolve_tenant(headers: Headers) -> str:
    """Return the tenant ID for this request, or raise.

    Raises:
        TenantResolutionError: when the ``Authorization`` header is missing,
            uses a non-Bearer scheme, or carries an unrecognized token.
    """
    value = headers.get("authorization")
    if value is None or not value.startswith(_BEARER_PREFIX):
        raise TenantResolutionError
    token = value[len(_BEARER_PREFIX) :]
    if token != _TENANT_T1_DEV_TOKEN:
        raise TenantResolutionError
    return _TENANT_T1
