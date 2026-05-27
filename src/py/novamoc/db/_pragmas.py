"""SQLite per-driver options registration.

The home for SQLAlchemy ``connect``-time PRAGMA listeners. Currently
sets ``journal_mode=WAL``; future per-connection pragmas
(``foreign_keys=ON``, ``synchronous=NORMAL``, etc.) live here so all
SQLite engine configuration is in one greppable place.

Listener registration is **per-engine**, not global. Callers explicitly
register the listener on engines they know are SQLite (typically
inside :func:`novamoc.db.config.build_alchemy_config` after the URL
scheme is inspected), so the listener body has no driver detection
of its own.

Tenant-scoping listeners live in :mod:`novamoc.db._listeners`;
keeping engine-level concerns (pragmas) separate from ORM-level
concerns (tenant scoping) is deliberate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.engine.interfaces import DBAPIConnection
    from sqlalchemy.ext.asyncio import AsyncEngine


def register_sqlite_pragmas(engine: AsyncEngine | Engine) -> None:
    """Attach the SQLite ``connect`` pragma listener to ``engine``.

    For async engines (``AsyncEngine``), SQLAlchemy fires connection
    events on the underlying ``sync_engine``; route there
    transparently. SQLAlchemy's event registry deduplicates
    ``(target, identifier, fn)`` tuples, so re-registering the same
    module-level listener on the same engine is a harmless no-op.
    """
    target = getattr(engine, "sync_engine", engine)
    event.listen(target, "connect", _set_sqlite_pragmas)


def _set_sqlite_pragmas(
    dbapi_connection: DBAPIConnection,
    _connection_record: object,
) -> None:
    """Apply SQLite per-connection PRAGMAs.

    The listener is only registered on engines the caller knows are
    SQLite, so no in-listener driver detection is needed. Today sets
    ``journal_mode=WAL``; WAL persists in the SQLite file header so
    the pragma is effectively idempotent. For ``:memory:`` databases
    SQLite returns ``memory`` mode silently and the pragma is a
    no-op.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.fetchone()
    finally:
        cursor.close()
