from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.extensions.litestar import repository, service
from sqlalchemy import func, select

import novamoc.db.models as m
from novamoc.domain.schema._commands import SchemaCommand


class SchemaChangeLogService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.SchemaChangeLog]
):
    """Append-only log of accepted schema commands.

    The repository pattern fits poorly here — the table is write-only from
    the endpoint's perspective and each row is one user action — but using
    advanced-alchemy's service keeps Litestar DI uniform across services.
    """

    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.SchemaChangeLog]):
        model_type = m.schema.SchemaChangeLog

    repository_type = Repo

    async def append(
        self,
        *,
        tenant_id: str,
        command: SchemaCommand,
        entity_id: UUID,
        payload: dict[str, Any],
    ) -> m.schema.SchemaChangeLog:
        # Per-tenant dense seq (issue #17). SQLite has no per-partition
        # identity; the next seq is computed here. The read-then-insert
        # is NOT serialised — aiosqlite/SQLAlchemy default to BEGIN
        # DEFERRED, and ADR-004's "single writer connection serialised
        # by the application layer" is intent, not yet enforced. Two
        # concurrent same-tenant POSTs can therefore both pick the same
        # next_seq; the composite PK on (tenant_id, seq) catches the
        # collision and the loser surfaces an IntegrityError (→ 500),
        # so there is no data corruption — only a request that the
        # client may retry. Tighten when the writer-serialisation pass
        # for ADR-004 lands.
        next_seq = await self.current_version(tenant_id=tenant_id) + 1
        return await self.create(
            data={
                "tenant_id": tenant_id,
                "seq": next_seq,
                "command": str(command.value),
                "entity_id": entity_id,
                "payload": payload,
            },
            auto_commit=False,
        )

    async def current_version(self, *, tenant_id: str) -> int:
        """Return ``MAX(seq)`` for the tenant, or ``0`` if none."""
        stmt = select(func.coalesce(func.max(m.schema.SchemaChangeLog.seq), 0)).where(
            m.schema.SchemaChangeLog.tenant_id == tenant_id
        )
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())
