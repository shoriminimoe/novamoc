"""Service wrappers for the events domain.

:class:`EventLogService` provides an advanced-alchemy repository over the
append-only ``event_log`` table (ADR-011). Same pattern as the schema
services; tenant scoping is supplied by the listener layer.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service
from sqlalchemy import func, select

from novamoc.db.models.data import EventLog


class EventLogService(service.SQLAlchemyAsyncRepositoryService[EventLog]):
    class Repo(repository.SQLAlchemyAsyncRepository[EventLog]):
        model_type = EventLog

    repository_type = Repo

    async def current_seq(self) -> int:
        """Return the tenant's current ``MAX(event_log.seq)`` (or 0).

        Tenant scope is supplied by Layer 1's aggregate-fallback path
        (``db._listeners._inject_tenant_filter``): this scalar aggregate
        has an empty ``state.all_mappers``, so ``with_loader_criteria``
        has nothing to attach to. The fallback walks the FROM clause,
        finds ``event_log``, and stamps ``WHERE tenant_id = <ctx>``
        directly on the Core ``Select``. Mirror of
        :meth:`SchemaChangeLogService.current_version`.
        """
        stmt = select(func.coalesce(func.max(EventLog.seq), 0))
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())


__all__ = ("EventLogService",)
