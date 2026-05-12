"""HTTP controller for ``/events`` (ADR-013).

Batch-level failures (``schema_version_stale``, malformed body) reject
the whole submission via ``application/problem+json``; per-event work
is atomic at the event grain (M1.5).

The controller is thin: one batch-level gate, a per-event HLC check,
and a dispatch call. The (family, body_type) handler — not the
controller — runs field/value validation *and* the ``event_log``
append, returning the per-event :class:`EventOutcome`. Any
``DomainError`` raised on the per-event path (HLC parse, HLC drift, or
the handler itself) is converted to a ``rejected:<code>`` outcome
carrying the same problem-details body the exception would render at
batch level — extras (``drift_seconds``, ``field``, ...) ride at the
top of ``EventOutcome.problem`` per RFC 9457 / ADR-016.

Batch-level: ``schema_version`` must equal the tenant's current schema
version (M1.3 / ADR-008 / ADR-009).

Per event, in order:

* HLC parse + drift check (M1.2 / ADR-006). The bad-shape and
  drift-exceeded paths raise ``PayloadShapeError`` /
  ``HLCDriftExceededError`` so the same problem-details translation
  runs as for handler errors.
* Handler dispatch (M1.4 + M1.5). The handler validates, appends to
  ``event_log`` in a savepoint, and returns ``accepted`` /
  ``duplicate``. A ``DomainError`` raised before the append becomes a
  rejected outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.api._problem_details import make_problem_body
from novamoc.domain._errors import DomainError, ErrorCode, PayloadShapeError
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._dispatch import dispatch
from novamoc.domain.events._errors import (
    HLCDriftExceededError,
    SchemaVersionStaleError,
)
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms
from novamoc.domain.events._payloads import (
    EventBatch,
    EventBatchResponse,
    EventOutcome,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
    SchemaChangeLogService,
)

if TYPE_CHECKING:
    from novamoc.domain.events._payloads import EventEnvelope


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


async def _provide_docs_base_url(state: State) -> str:
    return state.settings.app.docs_base_url


@dataclass(frozen=True, slots=True)
class AppendDeps:
    """DI-injectable bundle so :meth:`EventsController.append` takes one
    parameter instead of six.

    Public name (no underscore prefix) because Litestar's signature
    parser resolves the type at import time when binding the parameter.
    """

    drift_limit_seconds: float
    docs_base_url: str
    change_log: SchemaChangeLogService
    asset_field: AssetTypeFieldService
    record_field: MaintenanceRecordTypeFieldService
    event_log: EventLogService


async def _provide_append_deps(  # noqa: PLR0913  # one parameter per DI'd dep; Litestar pattern
    drift_limit_seconds: float,
    docs_base_url: str,
    schema_change_log_service: SchemaChangeLogService,
    asset_type_field_service: AssetTypeFieldService,
    maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
    event_log_service: EventLogService,
) -> AppendDeps:
    return AppendDeps(
        drift_limit_seconds=drift_limit_seconds,
        docs_base_url=docs_base_url,
        change_log=schema_change_log_service,
        asset_field=asset_type_field_service,
        record_field=maintenance_record_type_field_service,
        event_log=event_log_service,
    )


def _rejected(
    event: EventEnvelope, exc: DomainError, docs_base_url: str
) -> EventOutcome:
    """Build a rejected ``EventOutcome`` carrying ``exc``'s problem body.

    The problem dict matches the ``application/problem+json`` shape the
    same exception would render at batch level — clients can read
    extras (``drift_seconds``, ``field``, ...) the same way for both
    paths.
    """
    return EventOutcome(
        hlc=event.hlc,
        outcome=f"rejected:{exc.code.value}",
        problem=make_problem_body(exc, docs_base_url),
    )


@dataclass(frozen=True, slots=True)
class _BatchContext:
    """Constants shared by every event in one batch.

    ``server_now_ms`` is read once at the top of the controller so an
    event at the edge of the drift budget cannot get re-checked against
    a later server time mid-iteration.
    """

    server_now_ms: int
    drift_limit_seconds: float
    services: EventServiceBundle
    request: Request
    docs_base_url: str


async def _process_event(event: EventEnvelope, ctx: _BatchContext) -> EventOutcome:
    """HLC check then dispatch; map any ``DomainError`` to a rejected outcome."""
    try:
        parsed = HLC.parse(event.hlc)
    except HLCParseError as exc:
        return _rejected(
            event,
            PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message=str(exc),
                hlc=event.hlc,
            ),
            ctx.docs_base_url,
        )

    drift_seconds = (parsed.physical_ms - ctx.server_now_ms) / 1000
    if drift_seconds > ctx.drift_limit_seconds:
        return _rejected(
            event,
            HLCDriftExceededError(
                hlc=event.hlc,
                drift_seconds=drift_seconds,
                limit_seconds=ctx.drift_limit_seconds,
            ),
            ctx.docs_base_url,
        )

    try:
        return await dispatch(ctx.services, ctx.request.auth, event)
    except DomainError as exc:
        return _rejected(event, exc, ctx.docs_base_url)


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = (
        {
            "drift_limit_seconds": Provide(_provide_drift_limit_seconds),
            "docs_base_url": Provide(_provide_docs_base_url),
            "deps": Provide(_provide_append_deps),
        }
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
        | providers.create_service_dependencies(
            AssetTypeFieldService, "asset_type_field_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service"
        )
        | providers.create_service_dependencies(EventLogService, "event_log_service")
    )

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(
        self,
        data: EventBatch,
        request: Request,
        deps: AppendDeps,
    ) -> EventBatchResponse:
        # Batch-level schema-version gate. Runs before HLC parsing so a
        # stale-schema client sees the actionable error (re-fetch
        # /schema) instead of a downstream HLC complaint.
        current_version = await deps.change_log.current_version()
        if data.schema_version != current_version:
            raise SchemaVersionStaleError(
                expected=current_version,
                received=data.schema_version,
            )

        ctx = _BatchContext(
            server_now_ms=wall_now_ms(),
            drift_limit_seconds=deps.drift_limit_seconds,
            services=EventServiceBundle(
                asset_type_field_service=deps.asset_field,
                maintenance_record_type_field_service=deps.record_field,
                event_log_service=deps.event_log,
                schema_version=data.schema_version,
            ),
            request=request,
            docs_base_url=deps.docs_base_url,
        )

        outcomes = [await _process_event(event, ctx) for event in data.events]
        return EventBatchResponse(outcomes=tuple(outcomes))
