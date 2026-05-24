"""HTTP controller for ``GET /snapshot`` (M2.3, ADR-015).

Thin by design: bound checking lives in the Litestar ``Parameter(...)``
annotation, page-token decoding lives in the paginator, tenant scoping
is structural via the listener layer. The handler performs no manual
error mapping; ``ValidationException`` and ``PayloadShapeError`` both
funnel through the existing ``ProblemDetailsPlugin`` (ADR-016).

Two cursor-flavoured fields on the response are deliberately distinct
(see ``_payloads.SnapshotBatch``):

* The ``?page=`` query parameter (and the response's ``page`` field)
  is the opaque pagination continuation across the multi-batch
  transfer.
* The ``cursor`` field on the response (present only on the terminal
  batch) is the replication ``event_log.seq`` the client feeds to
  ``GET /events?cursor=`` for incremental catch-up.
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
    SNAPSHOT_DEFAULT_BATCH_SIZE,
    SNAPSHOT_MAX_BATCH_SIZE,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.snapshot._pagination import SnapshotPaginator
from novamoc.domain.snapshot._payloads import SnapshotBatch
from novamoc.domain.snapshot.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)


async def _provide_snapshot_paginator(  # noqa: PLR0913  # one parameter per DI'd dep; Litestar pattern
    schema_change_log_service: SchemaChangeLogService,
    event_log_service: EventLogService,
    asset_service: AssetService,
    asset_field_value_service: AssetFieldValueService,
    maintenance_record_service: MaintenanceRecordService,
    maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
) -> SnapshotPaginator:
    return SnapshotPaginator(
        change_log_service=schema_change_log_service,
        event_log_service=event_log_service,
        asset_service=asset_service,
        asset_field_value_service=asset_field_value_service,
        maintenance_record_service=maintenance_record_service,
        maintenance_record_field_value_service=maintenance_record_field_value_service,
    )


class SnapshotController(Controller):
    path = "/snapshot"
    tags = ("snapshot",)
    dependencies = (
        {"paginator": Provide(_provide_snapshot_paginator)}
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
        "/",
        responses={
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid page token or batch size",
                media_type="application/problem+json",
            ),
        },
    )
    async def read(
        self,
        paginator: SnapshotPaginator,
        page: str | None = None,
        results_per_page: Annotated[
            int, Parameter(ge=1, le=SNAPSHOT_MAX_BATCH_SIZE)
        ] = SNAPSHOT_DEFAULT_BATCH_SIZE,
    ) -> SnapshotBatch:
        return await paginator(page=page, results_per_page=results_per_page)
