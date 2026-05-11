"""HTTP controller for ``/events`` (ADR-013).

Batch-level failures (``schema_version_stale``, malformed body) reject
the whole submission via ``application/problem+json``; per-event work
is atomic at the event grain (M1.5).

The controller is thin: one batch-level gate, a per-event HLC check,
and a dispatch call. The (family, body_type) handler — not the
controller — runs field/value validation *and* the ``event_log``
append, returning the per-event :class:`EventOutcome`. The controller
maps any ``DomainError`` raised by the handler to a
``rejected:<code>`` outcome and aggregates the response.

Batch-level: ``schema_version`` must equal the tenant's current schema
version (M1.3 / ADR-008 / ADR-009).

Per event, in order:

* HLC parse + drift check (M1.2 / ADR-006) → ``rejected:invalid_payload_shape``
  or ``rejected:hlc_drift_exceeded``.
* Handler dispatch (M1.4 + M1.5). The handler validates, appends to
  ``event_log`` in a savepoint, and returns ``accepted`` / ``duplicate``.
  A ``DomainError`` raised before the append becomes
  ``rejected:<code>``.
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

from novamoc.domain._errors import DomainError, ErrorCode
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._dispatch import dispatch
from novamoc.domain.events._errors import SchemaVersionStaleError
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


@dataclass(frozen=True, slots=True)
class AppendDeps:
    """DI-injectable bundle so :meth:`EventsController.append` takes one
    parameter instead of five.

    Public name (no underscore prefix) because Litestar's signature
    parser resolves the type at import time when binding the parameter.
    """

    drift_limit_seconds: float
    change_log: SchemaChangeLogService
    asset_field: AssetTypeFieldService
    record_field: MaintenanceRecordTypeFieldService
    event_log: EventLogService


async def _provide_append_deps(
    drift_limit_seconds: float,
    schema_change_log_service: SchemaChangeLogService,
    asset_type_field_service: AssetTypeFieldService,
    maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
    event_log_service: EventLogService,
) -> AppendDeps:
    return AppendDeps(
        drift_limit_seconds=drift_limit_seconds,
        change_log=schema_change_log_service,
        asset_field=asset_type_field_service,
        record_field=maintenance_record_type_field_service,
        event_log=event_log_service,
    )


def _rejected(event: EventEnvelope, code: ErrorCode) -> EventOutcome:
    return EventOutcome(hlc=event.hlc, outcome=f"rejected:{code.value}")


async def _process_event(
    event: EventEnvelope,
    *,
    server_now_ms: int,
    limit_ms: int,
    services: EventServiceBundle,
    request: Request,
) -> EventOutcome:
    """HLC check then dispatch; map any ``DomainError`` to a rejected outcome."""
    try:
        parsed = HLC.parse(event.hlc)
    except HLCParseError:
        return _rejected(event, ErrorCode.INVALID_PAYLOAD_SHAPE)

    if parsed.physical_ms - server_now_ms > limit_ms:
        return _rejected(event, ErrorCode.HLC_DRIFT_EXCEEDED)

    try:
        return await dispatch(services, request.auth, event)
    except DomainError as exc:
        return _rejected(event, exc.code)


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = (
        {
            "drift_limit_seconds": Provide(_provide_drift_limit_seconds),
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

        # One server-now read covers the whole batch so an event at the
        # edge of the drift budget cannot get re-checked against a later
        # server time mid-iteration.
        server_now_ms = wall_now_ms()
        limit_ms = int(deps.drift_limit_seconds * 1000)

        services = EventServiceBundle(
            asset_type_field_service=deps.asset_field,
            maintenance_record_type_field_service=deps.record_field,
            event_log_service=deps.event_log,
            schema_version=data.schema_version,
        )

        outcomes: list[EventOutcome] = []
        for event in data.events:
            outcome = await _process_event(
                event,
                server_now_ms=server_now_ms,
                limit_ms=limit_ms,
                services=services,
                request=request,
            )
            outcomes.append(outcome)

        return EventBatchResponse(outcomes=tuple(outcomes))
