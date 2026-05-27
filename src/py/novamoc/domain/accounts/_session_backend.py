"""Request-scoped server-side session backend.

Upstream :class:`SQLAlchemyAsyncSessionBackend` opens a brand-new
:class:`~sqlalchemy.ext.asyncio.AsyncSession` via
``alchemy_config.get_session()`` for every ``set`` / ``delete`` call.
When the call fires from ``SessionMiddleware.wrapped_send`` at
``http.response.start`` time it lands on a *different* aiosqlite
connection than the one the request handler just wrote through, and
the two compete for the SQLite writer slot. Against a file-backed
database with the default ``AsyncAdaptedQueuePool`` that contention
manifested as ``OperationalError: database is locked`` (or, under
edge timing, ``attempt to write a readonly database``) — novamoc#123.

Folding the upsert into the same session
``alchemy_config.provide_session(state, scope)`` already caches on
the request scope makes the session-row write part of the request's
single transaction — exactly one writer per request, no
self-contention. ``get`` deliberately keeps the upstream behavior:
at SessionMiddleware *load* time (before any handler has run) the
request session has not been created yet, so opening an
independent short-lived read session for that path is fine.
"""

from __future__ import annotations

import contextvars
import datetime
from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar.session import (
    SESSION_ID_MAX_LENGTH,
    SQLAlchemyAsyncSessionBackend,
)
from advanced_alchemy.operations import OnConflictUpsert
from sqlalchemy import delete

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection
    from litestar.stores.base import Store
    from litestar.types import Message, ScopeSession


_current_connection: contextvars.ContextVar[ASGIConnection] = contextvars.ContextVar(
    "novamoc_session_backend_connection"
)


class RequestScopedSessionBackend(SQLAlchemyAsyncSessionBackend):
    """Session backend whose writes reuse the request-scoped AsyncSession."""

    async def store_in_message(
        self,
        scope_session: ScopeSession,
        message: Message,
        connection: ASGIConnection,
    ) -> None:
        # Upstream's set / delete signatures don't carry scope, so
        # bridge it through a contextvar set for the duration of the
        # super-class body. The reset on exit makes the leak path
        # invisible even if the upstream raises.
        token = _current_connection.set(connection)
        try:
            await super().store_in_message(scope_session, message, connection)
        finally:
            _current_connection.reset(token)

    async def set(self, /, session_id: str, data: bytes, store: Store) -> None:
        # ``store_in_message`` is the only documented caller for ``set``
        # / ``delete``, and it sets the contextvar before delegating
        # here. ``set`` invoked outside that path is a programming
        # error and surfaces as a ``LookupError`` from ``get()``.
        connection = _current_connection.get()
        session_id = session_id[:SESSION_ID_MAX_LENGTH]
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=self.config.max_age
        )

        db_session = self._alchemy.provide_session(
            connection.app.state, connection.scope
        )
        # On a 4xx/5xx response the ``autocommit`` before-send handler
        # has already rolled the request session back and left it
        # ``is_active=False``. Roll back explicitly to reset to a
        # clean transactional state before we issue our own write —
        # SessionMiddleware refreshes the session row regardless of
        # handler outcome.
        if not db_session.is_active:
            await db_session.rollback()
        dialect_name = db_session.bind.dialect.name
        upsert_stmt = OnConflictUpsert.create_upsert(
            table=self._model.__table__,  # ty: ignore[invalid-argument-type]
            values={"session_id": session_id, "data": data, "expires_at": expires_at},
            conflict_columns=["session_id"],
            update_columns=["data", "expires_at"],
            dialect_name=dialect_name,
            validate_identifiers=False,
        )
        await db_session.execute(upsert_stmt)
        await db_session.commit()

    async def delete(self, /, session_id: str, store: Store) -> None:
        connection = _current_connection.get()
        session_id = session_id[:SESSION_ID_MAX_LENGTH]
        db_session = self._alchemy.provide_session(
            connection.app.state, connection.scope
        )
        await db_session.execute(
            delete(self._model).where(self._model.session_id == session_id)
        )
        await db_session.commit()
