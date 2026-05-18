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
    id: str
    username: str
