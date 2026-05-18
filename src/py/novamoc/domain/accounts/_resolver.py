"""Tenant resolution from the request envelope.

v1: read the ``Authorization`` header, expect a ``Bearer <token>`` value,
match the token against a single hardcoded constant. On match return the
single dev-tenant UUID; on any failure raise ``TenantResolutionError``.

This module is the swap point. The v2 resolver will look up the session
cookie in the ``sessions`` table and load the user / membership it points
at (ADR-020); the middleware and DI layers do not change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from novamoc.domain.accounts._errors import TenantResolutionError

if TYPE_CHECKING:
    from litestar.datastructures import Headers

# Development-only credential. Anyone with checkout access can read it; that is
# the trust model for the dev period (ADR-017). Replaced by a real per-tenant
# token registry — see issue #19.
_TENANT_T1_DEV_TOKEN = "t1-dev-token"  # noqa: S105 — dev-only credential, see issue #19
# Pinned to match ``tests._constants.DEV_TENANT_ID`` so the test suite's
# canonical tenant resolves through the same code path production uses.
# The v2 resolver (M5.11) replaces this whole module with a session-cookie
# lookup against the ``tenants`` registry.
_TENANT_T1 = UUID("01900000-0000-7000-8000-000000000001")

_BEARER_PREFIX = "Bearer "


def resolve_tenant(headers: Headers) -> UUID:
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
