"""HTTP controller for ``/sync/initial`` (M2.3, ADR-015).

Thin by design: bound checking lives in the Litestar ``Parameter(...)``
annotation, cursor decoding lives in the paginator, tenant scoping is
structural via the listener layer. The handler performs no manual
error mapping; ``ValidationException`` and ``PayloadShapeError`` both
funnel through the existing ``ProblemDetailsPlugin`` (ADR-016).
"""

from __future__ import annotations

from typing import Annotated

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, get
from litestar.di import Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from novamoc.api._problem_details import ProblemDetails
from novamoc.config import (
    INITIAL_SYNC_DEFAULT_BATCH_SIZE,
    INITIAL_SYNC_MAX_BATCH_SIZE,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._pagination import InitialSyncPaginator
from novamoc.domain.sync._payloads import InitialSyncBatch
from novamoc.domain.sync.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)


async def _provide_initial_sync_paginator(  # noqa: PLR0913  # one parameter per DI'd dep; Litestar pattern
    schema_change_log_service: SchemaChangeLogService,
    event_log_service: EventLogService,
    asset_service: AssetService,
    asset_field_value_service: AssetFieldValueService,
    maintenance_record_service: MaintenanceRecordService,
    maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
) -> InitialSyncPaginator:
    return InitialSyncPaginator(
        change_log_service=schema_change_log_service,
        event_log_service=event_log_service,
        asset_service=asset_service,
        asset_field_value_service=asset_field_value_service,
        maintenance_record_service=maintenance_record_service,
        maintenance_record_field_value_service=maintenance_record_field_value_service,
    )


class SyncController(Controller):
    path = "/sync"
    tags = ("sync",)
    dependencies = (
        {"paginator": Provide(_provide_initial_sync_paginator)}
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
        | providers.create_service_dependencies(EventLogService, "event_log_service")
        | providers.create_service_dependencies(AssetService, "asset_service")
        | providers.create_service_dependencies(
            AssetFieldValueService, "asset_field_value_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordService, "maintenance_record_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordFieldValueService,
            "maintenance_record_field_value_service",
        )
    )

    @get(
        "/initial",
        responses={
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid cursor or batch size",
                media_type="application/problem+json",
            ),
        },
    )
    async def initial(
        self,
        paginator: InitialSyncPaginator,
        cursor: str | None = None,
        results_per_page: Annotated[
            int, Parameter(ge=1, le=INITIAL_SYNC_MAX_BATCH_SIZE)
        ] = INITIAL_SYNC_DEFAULT_BATCH_SIZE,
    ) -> InitialSyncBatch:
        return await paginator(cursor=cursor, results_per_page=results_per_page)
