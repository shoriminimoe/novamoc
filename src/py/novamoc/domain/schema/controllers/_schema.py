"""HTTP controller for the ``/schema`` routes.

``POST /schema`` accepts the discriminated union :data:`_payloads.SchemaRequest`
(Litestar publishes a ``oneOf`` discriminated by ``type`` in the OpenAPI
schema); dispatch is by the runtime variant class via :func:`dispatch`.

``GET /schema/{tenant_id}`` returns a ``SchemaSnapshotResponse`` —
the full per-tenant schema projection (all asset types and maintenance
record types with their nested fields, including tombstones) plus the
current ``schema_version``. The handler enforces the ``KNOWN_TENANT_IDS``
registry stub and raises ``TenantNotFoundError`` for unknown tenants.

Error rendering is the app-level ``ProblemDetailsPlugin`` registered in
``novamoc.asgi.create_app``: ``SchemaError``,
``msgspec.ValidationError``, and Litestar's ``ValidationException`` all
render as ``application/problem+json`` per ADR-016. The controller does
not register exception handlers itself.
"""

from __future__ import annotations

from uuid import UUID

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, Response, get, post
from litestar.openapi.datastructures import ResponseSpec

from novamoc.api._problem_details import ProblemDetails
from novamoc.config import KNOWN_TENANT_IDS
from novamoc.domain.schema import _payloads, services as _services
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema._errors import ErrorCode, TenantNotFoundError
from novamoc.domain.schema._read_payloads import (
    AssetTypeFieldView,
    AssetTypeView,
    MaintenanceRecordTypeFieldView,
    MaintenanceRecordTypeView,
    SchemaSnapshotResponse,
)


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

    @get(
        "/{tenant_id:str}",
        responses={
            304: ResponseSpec(
                None,
                description="Not Modified — If-None-Match matched current schema_version",
            ),
            404: ResponseSpec(
                ProblemDetails,
                description="Tenant not found",
                media_type="application/problem+json",
            ),
        },
    )
    async def get(
        self,
        request: Request,
        tenant_id: str,
        asset_type_service: _services.AssetTypeService,
        asset_type_field_service: _services.AssetTypeFieldService,
        maintenance_record_type_service: _services.MaintenanceRecordTypeService,
        maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
        schema_change_log_service: _services.SchemaChangeLogService,
    ) -> Response[SchemaSnapshotResponse | None]:
        # Snapshot consistency: every read in this handler runs on the same
        # request-scoped db_session injected by Litestar — one transaction,
        # one SQLite WAL snapshot. So `current_version` and the four
        # `list_for_tenant` reads see the same point-in-time, and the body
        # we return is internally consistent with the ETag we stamp on it.
        # If a concurrent POST commits during our request, we may be one
        # version behind by the time the response sends, but the next
        # request will see the new version (schema_version is monotonic) and
        # the If-None-Match comparison will correctly miss. Don't reorder
        # version vs projection reads expecting it to matter — under the
        # snapshot it doesn't, and `current_version` must run *before* the
        # If-None-Match check to enable the 304 short-circuit.
        if tenant_id not in KNOWN_TENANT_IDS:
            raise TenantNotFoundError(
                code=ErrorCode.TENANT_NOT_FOUND, tenant_id=tenant_id
            )

        schema_version = await schema_change_log_service.current_version(
            tenant_id=tenant_id
        )
        etag = f'"{schema_version}"'

        if request.headers.get("if-none-match") == etag:
            return Response(content=None, status_code=304, headers={"etag": etag})

        asset_types = await asset_type_service.list_for_tenant(tenant_id=tenant_id)
        asset_type_fields = await asset_type_field_service.list_for_tenant(
            tenant_id=tenant_id
        )
        record_types = await maintenance_record_type_service.list_for_tenant(
            tenant_id=tenant_id
        )
        record_type_fields = (
            await maintenance_record_type_field_service.list_for_tenant(
                tenant_id=tenant_id
            )
        )

        fields_by_asset_type: dict[UUID, list[AssetTypeFieldView]] = {}
        for f in asset_type_fields:
            fields_by_asset_type.setdefault(f.parent_id, []).append(
                AssetTypeFieldView(
                    id=f.id,
                    name=f.name,
                    data_type=f.data_type,
                    validation=f.validation,
                    active=f.active,
                )
            )

        fields_by_record_type: dict[UUID, list[MaintenanceRecordTypeFieldView]] = {}
        for f in record_type_fields:
            fields_by_record_type.setdefault(f.parent_id, []).append(
                MaintenanceRecordTypeFieldView(
                    id=f.id,
                    name=f.name,
                    data_type=f.data_type,
                    validation=f.validation,
                    active=f.active,
                )
            )

        snapshot = SchemaSnapshotResponse(
            schema_version=schema_version,
            asset_types=tuple(
                AssetTypeView(
                    id=t.id,
                    name=t.name,
                    active=t.active,
                    fields=tuple(fields_by_asset_type.get(t.id, ())),
                )
                for t in asset_types
            ),
            maintenance_record_types=tuple(
                MaintenanceRecordTypeView(
                    id=t.id,
                    name=t.name,
                    active=t.active,
                    fields=tuple(fields_by_record_type.get(t.id, ())),
                )
                for t in record_types
            ),
        )
        return Response(
            content=snapshot,
            headers={"etag": etag},
        )
