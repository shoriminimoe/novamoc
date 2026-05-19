"""Read-only service wrappers for the projection tables.

Identical shape to :class:`novamoc.domain.events.services.EventLogService`
— advanced-alchemy repositories over the four projection models. The
write path is the events fold (see ``domain/events/_fold.py``,
``_projection.py``, ``_row_state.py``); these services are used only
by the initial-sync paginator for ordered reads.

Tenant scoping is structural: every ``.list(...)`` goes through Layer 1
of ``db._listeners`` and is filtered to the active tenant.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)


class AssetService(service.SQLAlchemyAsyncRepositoryService[Asset]):
    class Repo(repository.SQLAlchemyAsyncRepository[Asset]):
        model_type = Asset

    repository_type = Repo


class AssetFieldValueService(service.SQLAlchemyAsyncRepositoryService[AssetFieldValue]):
    class Repo(repository.SQLAlchemyAsyncRepository[AssetFieldValue]):
        model_type = AssetFieldValue

    repository_type = Repo


class MaintenanceRecordService(
    service.SQLAlchemyAsyncRepositoryService[MaintenanceRecord]
):
    class Repo(repository.SQLAlchemyAsyncRepository[MaintenanceRecord]):
        model_type = MaintenanceRecord

    repository_type = Repo


class MaintenanceRecordFieldValueService(
    service.SQLAlchemyAsyncRepositoryService[MaintenanceRecordFieldValue]
):
    class Repo(repository.SQLAlchemyAsyncRepository[MaintenanceRecordFieldValue]):
        model_type = MaintenanceRecordFieldValue

    repository_type = Repo


__all__ = (
    "AssetFieldValueService",
    "AssetService",
    "MaintenanceRecordFieldValueService",
    "MaintenanceRecordService",
)
