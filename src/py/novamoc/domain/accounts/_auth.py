"""Per-request authentication scope.

Produced by :class:`AuthenticationMiddleware`, written into
``scope["auth"]`` via the framework's ``AuthenticationResult.auth``
slot, and handed to handlers via the :func:`provide_auth` DI provider.

The shape mirrors Litestar's ``user`` / ``auth`` split: the *principal*
(who the requester is) lives on ``scope["user"]``; the *active scope*
of this request — credential-derived, varies per request — lives here.
v1 carries only the active tenant id. Future fields slot in as the
credential format grows (token id, scopes, expires_at, actor kind).

Why "scope, not principal" for tenant id: a user may have access to
multiple tenants but each request operates within exactly one. Putting
the active tenant on ``auth`` keeps the principal stable across
requests and frees future "switch tenant" flows from any User-shape
refactor.
"""

from __future__ import annotations

import msgspec


class RequestAuth(msgspec.Struct, frozen=True):
    tenant_id: str
