"""HTTP controller for the ``/schema`` routes.

``POST /schema`` accepts the discriminated union :data:`_payloads.SchemaRequest`
(Litestar publishes a ``oneOf`` discriminated by ``type`` in the OpenAPI
schema); dispatch is by the runtime variant class via :func:`dispatch`.

``GET /schema`` returns a ``SchemaSnapshotResponse`` — the full
per-tenant schema projection (all asset types and maintenance record
types with their nested fields, including tombstones) plus the current
``schema_version``. The handler does not read the tenant id directly:
``TenantContextMiddleware`` (mounted upstream in ``asgi.create_app``)
sets ``current_tenant_id`` from ``request.auth.tenant_id`` before the
handler runs, and Layer 1 of the tenant-scoping listeners
(``db._listeners``) supplies the ``WHERE tenant_id = ...`` predicate
on every read. A missing or invalid bearer token is rejected upstream
by ``AuthenticationMiddleware`` before either middleware runs.

``GET /schema/changes`` streams ``schema_change_log`` rows with
``seq > since``, ordered ascending, bounded by a configurable batch
size. The same ``TenantContextMiddleware`` + Layer 1 listener path
supplies the tenant predicate. Bounds errors on ``since`` / ``limit``
render through the existing ``ProblemDetailsPlugin`` as
``invalid_payload_shape``.

``POST /schema``'s ``apply_command`` reads ``request.auth`` directly
because the dispatch table passes ``RequestAuth`` through to handlers
that need it for ``update``/``delete`` ``item_id`` tuples. ``request.auth``
is populated by ``AuthenticationMiddleware`` — Litestar's standard
attribute access, not a DI provider.

Error rendering is the app-level ``ProblemDetailsPlugin`` registered in
``novamoc.asgi.create_app``: ``DomainError``,
``msgspec.ValidationError``, and Litestar's ``ValidationException`` all
render as ``application/problem+json`` per ADR-016. The controller does
not register exception handlers itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import providers
from advanced_alchemy.filters import OrderBy
from litestar import Controller, Request, Response, get, post
from litestar.datastructures import (
    ETag,
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.pagination import CursorPagination

from novamoc.api._problem_details import ProblemDetails
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.schema import _payloads
from novamoc.domain.schema import services as _services
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema._read_payloads import (
    AssetTypeFieldView,
    AssetTypeView,
    MaintenanceRecordTypeFieldView,
    MaintenanceRecordTypeView,
    SchemaChangeView,
    SchemaSnapshotResponse,
)

if TYPE_CHECKING:
    from uuid import UUID


async def _provide_max_batch_size(state: State) -> int:
    return state.settings.app.schema_changes_max_batch_size


def _matches_current_etag(if_none_match: str | None, current: ETag) -> bool:
    """Return True if the request's ``If-None-Match`` matches ``current``.

    Strong comparison only (RFC 7232 §2.3.2): we issue strong ETags, so an
    inbound ``W/"<value>"`` is not a cache hit even if the value matches.
    The ``*`` wildcard always matches per RFC 7232 §3.2 (the precondition
    fails when a current representation exists, which is always true for
    a successful read of an existing tenant).
    """
    if if_none_match is None:
        return False
    if if_none_match == "*":
        return True
    parsed = ETag.from_header(if_none_match)
    return parsed.value == current.value and not parsed.weak


class SchemaController(Controller):
    path = "/schema"
    tags = ["schema"]

    dependencies = (
        {
            "max_batch_size": Provide(_provide_max_batch_size),
        }
        | providers.create_service_dependencies(
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
    async def apply_command(
        self,
        data: _payloads.SchemaRequest,
        request: Request,
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
        outcome = await dispatch(services, request.auth, data)
        return _payloads.SchemaResponse(
            schema_version=outcome.schema_version,
            entity_id=outcome.entity_id,
            outcome=outcome.outcome.value,
            committed_at=outcome.committed_at,
        )

    @get(
        "/",
        etag=ETag(documentation_only=True),
        responses={
            200: ResponseSpec(
                SchemaSnapshotResponse,
                description="Per-tenant schema snapshot",
            ),
            304: ResponseSpec(
                None,
                description="Not Modified — If-None-Match matched current schema_version",
            ),
            401: ResponseSpec(
                ProblemDetails,
                description="Tenant could not be resolved from request",
                media_type="application/problem+json",
            ),
        },
    )
    async def read_snapshot(
        self,
        request: Request,
        asset_type_service: _services.AssetTypeService,
        asset_type_field_service: _services.AssetTypeFieldService,
        maintenance_record_type_service: _services.MaintenanceRecordTypeService,
        maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
        schema_change_log_service: _services.SchemaChangeLogService,
    ) -> Response[SchemaSnapshotResponse | None]:
        # Snapshot consistency: every read in this handler runs on the same
        # request-scoped db_session injected by Litestar — one transaction,
        # one SQLite WAL snapshot. So `current_version` and the four
        # `list` reads see the same point-in-time, and the body we return is
        # internally consistent with the ETag we stamp on it. If a concurrent
        # POST commits during our request, we may be one version behind by the
        # time the response sends, but the next request will see the new
        # version (schema_version is monotonic) and the If-None-Match
        # comparison will correctly miss. Don't reorder version vs projection
        # reads expecting it to matter — under the snapshot it doesn't, and
        # `current_version` must run *before* the If-None-Match check to
        # enable the 304 short-circuit.
        schema_version = await schema_change_log_service.current_version()
        current_etag = ETag(value=str(schema_version))

        if _matches_current_etag(request.headers.get("if-none-match"), current_etag):
            not_modified: Response[SchemaSnapshotResponse | None] = Response(
                content=None, status_code=304
            )
            not_modified.set_etag(current_etag)
            return not_modified

        # ORDER BY clauses are load-bearing: the strong ETag (RFC 7232 §2.3
        # byte-equality) requires that two responses for the same
        # schema_version produce byte-identical bodies.
        asset_types = await asset_type_service.list(OrderBy(field_name="id"))
        asset_type_fields = await asset_type_field_service.list(
            OrderBy(field_name="parent_id"), OrderBy(field_name="id")
        )
        record_types = await maintenance_record_type_service.list(
            OrderBy(field_name="id")
        )
        record_type_fields = await maintenance_record_type_field_service.list(
            OrderBy(field_name="parent_id"), OrderBy(field_name="id")
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
        snapshot_response: Response[SchemaSnapshotResponse | None] = Response(
            content=snapshot
        )
        snapshot_response.set_etag(current_etag)
        return snapshot_response

    @get(
        "/changes",
        responses={
            200: ResponseSpec(
                CursorPagination[int, SchemaChangeView],
                description="Page of schema change log rows for the active tenant",
            ),
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid since/limit query parameter",
                media_type="application/problem+json",
            ),
            401: ResponseSpec(
                ProblemDetails,
                description="Tenant could not be resolved from request",
                media_type="application/problem+json",
            ),
        },
    )
    async def read_changes(
        self,
        schema_change_log_service: _services.SchemaChangeLogService,
        max_batch_size: int,
        since: int = 0,
        limit: int | None = None,
    ) -> CursorPagination[int, SchemaChangeView]:
        # Range checks. INVALID_PAYLOAD_SHAPE is the existing code for
        # "the request couldn't be decoded against the expected shape" — see
        # the design spec. We do them here rather than via Parameter(ge=...,
        # le=...) because the upper bound is settings-derived and not a
        # literal at class-body parse time.
        if since < 0:
            raise PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message="since must be >= 0",
                field="since",
                received=since,
            )
        effective_limit = max_batch_size if limit is None else limit
        if effective_limit < 1 or effective_limit > max_batch_size:
            raise PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message=(f"limit must be between 1 and {max_batch_size} inclusive"),
                field="limit",
                received=limit,
                max=max_batch_size,
            )

        # Snapshot consistency: current_version and the page read share the
        # same request-scoped session, so they observe one WAL snapshot.
        # Read current_version FIRST so the has-more decision is made
        # against the same point-in-time as the page contents.
        current_version = await schema_change_log_service.current_version()
        rows = await schema_change_log_service.list_changes_after(
            since=since, limit=effective_limit
        )

        items = [
            SchemaChangeView(
                seq=r.seq,
                command=r.command,
                entity_id=r.entity_id,
                payload=r.payload,
                committed_at=r.committed_at,
                actor_id=r.actor_id,
            )
            for r in rows
        ]
        # CursorPagination convention: ``cursor`` in the response is the
        # next cursor (the seq to pass as ``since`` on the next request).
        # ``None`` means caught up — no more rows beyond the last returned
        # one. ADR-009's catch-up loop terminates when this is None.
        next_cursor = (
            items[-1].seq if items and items[-1].seq < current_version else None
        )
        return CursorPagination[int, SchemaChangeView](
            items=items,
            results_per_page=effective_limit,
            cursor=next_cursor,
        )
