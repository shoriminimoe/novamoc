"""Per-request principal.

Lands on ``scope["user"]``. ADR-017's principal/scope split holds — the
principal is stable across requests, the scope (:class:`RequestAuth`)
varies. Deliberately minimal: no ``password_hash``, no ``disabled_at``,
no membership list — those live on the SQLAlchemy ``User`` row, not on
a request-scoped object.
"""

# `Principal` is a msgspec Struct introspected at runtime by Litestar
# (request-scope decoding via `request.user`); field-annotation imports
# stay at runtime.

from __future__ import annotations

import msgspec


class Principal(msgspec.Struct, frozen=True):
    # ``id`` is intentionally ``str`` (not ``uuid.UUID``) even though the
    # underlying ``users.id`` column is a UUIDv7. ``Principal`` lands on
    # ``scope["user"]`` and is consumed by :class:`MePrincipal` (the
    # ``/auth/me`` wire shape, also ``id: str``); keeping both ``str``
    # avoids stringifying twice per request. ``RequestAuth.tenant_id``
    # stays a ``uuid.UUID`` because it travels into the storage-layer
    # ContextVar — that side wants the native type.
    id: str
    username: str
