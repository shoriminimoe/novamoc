"""Service wrappers for the events domain.

:class:`EventLogService` provides an advanced-alchemy repository over the
append-only ``event_log`` table (ADR-011). Same pattern as the schema
services; tenant scoping is supplied by the listener layer.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models.data import EventLog


class EventLogService(service.SQLAlchemyAsyncRepositoryService[EventLog]):
    class Repo(repository.SQLAlchemyAsyncRepository[EventLog]):
        model_type = EventLog

    repository_type = Repo


__all__ = ("EventLogService",)
