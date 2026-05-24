"""Server-side session storage model (ADR-020, M5.7).

Layering note: ``SessionModelMixin`` is only importable from
``advanced_alchemy.extensions.litestar.session`` — it is not re-exported
from ``advanced_alchemy.base`` or any other non-litestar path.  This file
is the single deliberate exception to CLAUDE.md's "Critical layering rule"
(db/ must not import ``advanced_alchemy.extensions.litestar``).  The
exception is justified because the mixin is purely a storage-layer
declaration: it defines the ``sessions`` table columns and carries no
Litestar request/response wiring.  The actual cookie and middleware
configuration lives in ``asgi.py`` (M5.11); nothing here depends on a
live Litestar application object.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar.session import (
    SessionModelMixin,
)


class Session(SessionModelMixin):
    """Server-side session row (ADR-020).

    Inherits ``id`` (UUIDv7), ``session_id``, ``data``, and ``expires_at``
    from :class:`~advanced_alchemy.extensions.litestar.session.SessionModelMixin`.
    Not tenant-scoped — session rows are global identity records.

    The ``SessionModelMixin`` base class extends ``UUIDv7Base``, which is
    registered on the same SQLAlchemy ``metadata`` / ``registry`` instance
    as ``DefaultBase``; the table therefore appears on the shared metadata
    and is created alongside all other project tables.
    """

    __tablename__ = "sessions"
