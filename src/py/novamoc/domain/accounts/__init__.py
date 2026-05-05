"""Tenant resolution from the request envelope (ADR-017).

This package owns: the per-request ``RequestAuth`` (credential-derived
scope), the ``resolve_tenant`` function (the credential-shape swap
point), the ``AuthenticationMiddleware`` that calls it, and the
``TenantResolutionError`` raised on resolution failure.

Handlers receive the resolved auth value via Litestar's standard
``request.auth`` accessor — no DI provider. The middleware writes into
``scope["auth"]`` via the framework's ``AuthenticationResult.auth``
slot; ``request.auth`` is the typed read of that slot.
"""

from __future__ import annotations

from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._middleware import AuthenticationMiddleware
from novamoc.domain.accounts._resolver import resolve_tenant

__all__ = (
    "AuthenticationMiddleware",
    "RequestAuth",
    "TenantResolutionError",
    "resolve_tenant",
)
