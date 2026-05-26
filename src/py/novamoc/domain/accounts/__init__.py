"""Tenant resolution + authentication (ADR-017, ADR-020).

This package owns: the per-request ``RequestAuth`` (credential-derived
scope) and ``Principal`` (who the requester is), the
session-cookie-backed
:func:`resolve_principal_from_session` (the credential-format swap
point), the :class:`AuthenticationMiddleware` that calls it, the
:class:`TenantContextMiddleware` that binds the resolved
``tenant_id`` to the storage-layer ContextVar, and the typed errors
the auth surface raises.

Handlers receive the resolved values via Litestar's standard
``request.user`` / ``request.auth`` accessors — no DI provider. The
authentication middleware writes them into ``scope["user"]`` /
``scope["auth"]`` via the framework's ``AuthenticationResult.user``
and ``AuthenticationResult.auth`` slots; ``request.user`` and
``request.auth`` are the typed reads of those slots.
"""

from __future__ import annotations

from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import (
    LoginFailedError,
    TenantResolutionError,
    UserAlreadyHasTenantError,
)
from novamoc.domain.accounts._middleware import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
)
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._principal import Principal
from novamoc.domain.accounts._resolver import resolve_principal_from_session
from novamoc.domain.accounts.controllers import AuthController

__all__ = (
    "AuthController",
    "AuthenticationMiddleware",
    "LoginFailedError",
    "PasswordHasher",
    "Principal",
    "RequestAuth",
    "TenantContextMiddleware",
    "TenantResolutionError",
    "UserAlreadyHasTenantError",
    "resolve_principal_from_session",
)
