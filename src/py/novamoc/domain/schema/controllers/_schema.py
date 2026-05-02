"""HTTP controller for ``POST /schema``.

The route's request body is the discriminated union :data:`_payloads.SchemaRequest`,
so Litestar publishes a ``oneOf`` discriminated by ``type`` in the
OpenAPI schema. Dispatch is by the runtime variant class via
:func:`dispatch`.

The exception handlers map ``SchemaCommandError`` and the two
validation-error classes (msgspec's and Litestar's wrapper) to the JSON
envelope documented in the design spec.

**On the built-in path.** Litestar's mechanism for custom error
envelopes is the ``exception_handlers`` mapping registered on a
controller (or app). Subclassing ``litestar.exceptions.HTTPException``
gets you a default render of ``{status_code, detail, extra}`` — useful
when the default shape fits, less useful when the envelope must be
``{error, code, message, ...extras}`` like ours. We keep
``SchemaCommandError`` as a plain ``Exception`` and let the registered
handler produce the envelope; this *is* the built-in path, just with a
custom renderer rather than the default HTTPException one.
"""

from __future__ import annotations

from typing import Any

import msgspec
from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, Response, post
from litestar.exceptions import ValidationException
from litestar.openapi.datastructures import ResponseSpec
from litestar.status_codes import HTTP_400_BAD_REQUEST

from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema import _payloads, services as _services
from novamoc.domain.schema._errors import ErrorCode, SchemaCommandError


def schema_command_error_handler(
    _request: Request[Any, Any, Any] | None, exc: SchemaCommandError,
) -> Response[dict[str, Any]]:
    body: dict[str, Any] = {
        "error": exc.error,
        "code": exc.code.value,
        "message": exc.message,
    }
    body.update(exc.extras)
    return Response(content=body, status_code=exc.status_code)


def msgspec_validation_error_handler(
    _request: Request[Any, Any, Any] | None, exc: msgspec.ValidationError,
) -> Response[dict[str, Any]]:
    return Response(
        content={
            "error": "invalid_request",
            "code": ErrorCode.INVALID_PAYLOAD_SHAPE.value,
            "message": str(exc),
        },
        status_code=HTTP_400_BAD_REQUEST,
    )


def litestar_validation_error_handler(
    _request: Request[Any, Any, Any] | None, exc: ValidationException,
) -> Response[dict[str, Any]]:
    """Map Litestar's ``ValidationException`` (which wraps msgspec decode errors)
    to the same ``invalid_payload_shape`` envelope used for raw msgspec errors.
    """
    return Response(
        content={
            "error": "invalid_request",
            "code": ErrorCode.INVALID_PAYLOAD_SHAPE.value,
            "message": exc.detail or str(exc),
        },
        status_code=HTTP_400_BAD_REQUEST,
    )


class SchemaController(Controller):
    path = "/schema"
    tags = ["schema"]

    dependencies = (
        providers.create_service_dependencies(_services.AssetTypeService, "asset_type_service")
        | providers.create_service_dependencies(
            _services.AssetTypeFieldService, "asset_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeService, "maintenance_record_type_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.SchemaChangeLogService, "schema_change_log_service",
        )
    )

    exception_handlers = {  # type: ignore[var-annotated]
        SchemaCommandError: schema_command_error_handler,
        msgspec.ValidationError: msgspec_validation_error_handler,
        ValidationException: litestar_validation_error_handler,
    }

    @post(
        "/",
        responses={
            400: ResponseSpec(_payloads.SchemaErrorResponse, description="Invalid request"),
            404: ResponseSpec(_payloads.SchemaErrorResponse, description="Entity not found"),
            409: ResponseSpec(_payloads.SchemaErrorResponse, description="Conflict"),
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
