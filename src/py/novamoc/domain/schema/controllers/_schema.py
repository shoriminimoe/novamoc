"""HTTP controller for ``POST /schema``.

The route's request body is the discriminated union :data:`_payloads.SchemaRequest`,
so Litestar publishes a ``oneOf`` discriminated by ``type`` in the
OpenAPI schema. Dispatch is by the runtime variant class via
:func:`dispatch`.

Error rendering is the app-level ``ProblemDetailsPlugin`` registered in
``novamoc.asgi.create_app``: ``SchemaError``,
``msgspec.ValidationError``, and Litestar's ``ValidationException`` all
render as ``application/problem+json`` per ADR-016. The controller does
not register exception handlers itself.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, post
from litestar.openapi.datastructures import ResponseSpec

from novamoc.api._problem_details import ProblemDetails
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema import _payloads, services as _services


class SchemaController(Controller):
    path = "/schema"
    tags = ["schema"]

    dependencies = (
        providers.create_service_dependencies(
            _services.AssetTypeService, "asset_type_service"
        )
        | providers.create_service_dependencies(
            _services.AssetTypeFieldService,
            "asset_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeService,
            "maintenance_record_type_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeFieldService,
            "maintenance_record_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.SchemaChangeLogService,
            "schema_change_log_service",
        )
    )

    @post(
        "/",
        responses={
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid request",
                media_type="application/problem+json",
            ),
            404: ResponseSpec(
                ProblemDetails,
                description="Entity not found",
                media_type="application/problem+json",
            ),
            409: ResponseSpec(
                ProblemDetails,
                description="Conflict",
                media_type="application/problem+json",
            ),
        },
    )
    async def post(
        self,
        data: _payloads.SchemaRequest,
        asset_type_service: _services.AssetTypeService,
        asset_type_field_service: _services.AssetTypeFieldService,
        maintenance_record_type_service: _services.MaintenanceRecordTypeService,
        maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
        schema_change_log_service: _services.SchemaChangeLogService,
    ) -> _payloads.SchemaResponse:
        services = ServiceBundle(
            asset_type=asset_type_service,
            asset_type_field=asset_type_field_service,
            maintenance_record_type=maintenance_record_type_service,
            maintenance_record_type_field=maintenance_record_type_field_service,
            change_log=schema_change_log_service,
        )
        outcome = await dispatch(services, data)
        return _payloads.SchemaResponse(
            schema_version=outcome.schema_version,
            entity_id=outcome.entity_id,
            outcome=outcome.outcome.value,
            committed_at=outcome.committed_at,
        )
