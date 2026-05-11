"""HTTP controller for ``/events`` (ADR-013).

The controller runs the request through one batch-level gate and a
per-event pipeline. Batch-level failures (``schema_version_stale``,
malformed body) reject the whole submission via
``application/problem+json``; per-event outcomes are atomic at the
event grain (M1.5).

1. **Schema-version gate** (batch-level, M1.3 / ADR-008 / ADR-009): the
   batch's ``schema_version`` must equal the tenant's current schema
   version. A mismatch raises ``schema_version_stale``.

For each event in order:

* HLC parse + drift check (M1.2, ADR-006). Malformed HLCs and HLCs
  more than ``AppSettings.hlc_drift_limit_seconds`` ahead of the
  server are reported as ``rejected:invalid_payload_shape`` and
  ``rejected:hlc_drift_exceeded`` respectively.
* Handler dispatch (M1.4). The ``(family, body_type)`` handler runs
  field-existence + value-shape validation; the controller does not
  import ``_validators`` directly. Domain errors raised by the
  handler are reported as ``rejected:<code>``.
* Append to ``event_log`` (M1.5, ADR-011). A row whose
  ``UNIQUE(tenant_id, hlc)`` collides with an existing row is
  reported as ``duplicate`` (idempotent re-delivery). Inserts run
  inside a ``begin_nested()`` savepoint so an ``IntegrityError`` on
  one event leaves the surrounding transaction usable for the next.

Projection writes (field-value LWW, row state, entity-table updates)
land in M1.6+. This controller currently only writes to
``event_log``; the fold runs against that log later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import msgspec
from advanced_alchemy.exceptions import IntegrityError as RepositoryIntegrityError
from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.db.models.data import EventOp
from novamoc.domain._errors import DomainError, ErrorCode
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._dispatch import dispatch
from novamoc.domain.events._errors import SchemaVersionStaleError
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms
from novamoc.domain.events._payloads import (
    Deactivated,
    EntityFamily,
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
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._payloads import EventEnvelope


# Map each entity family to the projection table_name recorded on the
# event_log row. The fold (M1.6+) routes on this column.
_TABLE_NAMES: Final[dict[EntityFamily, str]] = {
    EntityFamily.ASSET: "assets",
    EntityFamily.MAINTENANCE_RECORD: "maintenance_records",
}


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


@dataclass(frozen=True, slots=True)
class AppendDeps:
    """Aggregated dependencies for :meth:`EventsController.append`.

    Bundles services + tunables into one DI-injectable container so
    the handler signature stays narrow. Public name (no underscore
    prefix) because Litestar's signature parser resolves the type at
    import time when binding the parameter.
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


def _op_for_body(body: object) -> EventOp:
    """``deactivated`` events are deletes; everything else is a set."""
    if isinstance(body, Deactivated):
        return EventOp.DELETE
    return EventOp.SET


def _value_json_for_body(body: object) -> dict[str, Any] | None:
    """Round-trip the body through msgspec so the stored payload
    matches the wire shape. ``Deactivated`` carries no payload."""
    if isinstance(body, Deactivated):
        return None
    return msgspec.to_builtins(body)


class _RejectOutcomeError(Exception):
    """Sentinel raised by per-event validators to short-circuit the
    pipeline with a ``rejected:<code>`` outcome."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


async def _validate_event(
    event: EventEnvelope,
    *,
    server_now_ms: int,
    limit_ms: int,
    services: EventServiceBundle,
    auth: RequestAuth,
) -> None:
    """Run M1.2 HLC + M1.4 dispatch checks for one event.

    Raises:
        _RejectOutcomeError: validation failed; the caller maps the
            attached ``code`` to a ``rejected:<code>`` outcome.
    """
    try:
        parsed = HLC.parse(event.hlc)
    except HLCParseError as exc:
        raise _RejectOutcomeError(ErrorCode.INVALID_PAYLOAD_SHAPE) from exc

    drift_ms = parsed.physical_ms - server_now_ms
    if drift_ms > limit_ms:
        raise _RejectOutcomeError(ErrorCode.HLC_DRIFT_EXCEEDED)

    try:
        await dispatch(services, auth, event)
    except DomainError as exc:
        raise _RejectOutcomeError(exc.code) from exc


async def _append_one(
    event: EventEnvelope,
    *,
    schema_version: int,
    event_log_service: EventLogService,
) -> EventOutcome:
    """Insert one ``event_log`` row inside a savepoint.

    The savepoint isolates the ``IntegrityError`` path so the outer
    transaction — committed at response time by the autocommit
    handler — stays usable for subsequent events in the batch.

    Returns:
        ``accepted`` or ``duplicate`` outcome.
    """
    session = event_log_service.repository.session
    try:
        async with session.begin_nested():
            await event_log_service.create(
                data={
                    "hlc": event.hlc,
                    "schema_version": schema_version,
                    "table_name": _TABLE_NAMES[event.family],
                    "entity_id": str(event.instance_id),
                    "field_id": None,
                    "op": _op_for_body(event.body),
                    "value_json": _value_json_for_body(event.body),
                },
                auto_commit=False,
            )
    except RepositoryIntegrityError:
        # advanced_alchemy wraps SQLAlchemy IntegrityError into its own
        # taxonomy (DuplicateKeyError extends this). The savepoint
        # rolled back, so the outer transaction is still usable.
        return EventOutcome(hlc=event.hlc, outcome="duplicate")
    return EventOutcome(hlc=event.hlc, outcome="accepted")


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
        # 1. Batch-level schema-version gate. Runs before HLC parsing so a
        # stale-schema client sees the actionable error (re-fetch /schema)
        # instead of a downstream HLC complaint.
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
        )

        outcomes: list[EventOutcome] = []
        for event in data.events:
            try:
                await _validate_event(
                    event,
                    server_now_ms=server_now_ms,
                    limit_ms=limit_ms,
                    services=services,
                    auth=request.auth,
                )
            except _RejectOutcomeError as rej:
                outcomes.append(
                    EventOutcome(hlc=event.hlc, outcome=f"rejected:{rej.code.value}")
                )
                continue

            outcome = await _append_one(
                event,
                schema_version=data.schema_version,
                event_log_service=deps.event_log,
            )
            outcomes.append(outcome)

        return EventBatchResponse(outcomes=tuple(outcomes))
