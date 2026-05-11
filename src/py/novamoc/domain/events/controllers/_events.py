"""HTTP controller for ``/events`` (ADR-013).

The controller enforces three pre-persistence batch gates and then
delegates each event to its handler:

1. **Schema-version gate** (batch-level, M1.3 / ADR-008 / ADR-009): the
   batch's ``schema_version`` must equal the tenant's current schema
   version. A mismatch raises ``schema_version_stale``.
2. **HLC parse + drift bound** (per-event, M1.2 / ADR-006): each event's
   ``hlc`` is parsed; an HLC whose physical component sits more than
   ``AppSettings.hlc_drift_limit_seconds`` ahead of server wall time is
   rejected as ``hlc_drift_exceeded``. Past HLCs are always accepted —
   drift is one-sided.
3. **Per-event handler dispatch** (M1.4): each event is routed to the
   handler matching ``(event.family, type(event.body))``. Today the
   handlers do field-existence + value-shape validation; M1.5+ layers
   persistence, projection writes, and business rules into the same
   cells.

The controller does not import ``_validators`` — that machinery is
called by the handlers, not by the controller.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.domain.events import _payloads
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._dispatch import dispatch
from novamoc.domain.events._errors import (
    HLCDriftExceededError,
    SchemaVersionStaleError,
)
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
    SchemaChangeLogService,
)


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = (
        {"drift_limit_seconds": Provide(_provide_drift_limit_seconds)}
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
        | providers.create_service_dependencies(
            AssetTypeFieldService, "asset_type_field_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service"
        )
    )

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(  # noqa: PLR0913  # one parameter per DI'd service; Litestar pattern
        self,
        data: _payloads.EventBatch,
        request: Request,
        drift_limit_seconds: float,
        schema_change_log_service: SchemaChangeLogService,
        asset_type_field_service: AssetTypeFieldService,
        maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
    ) -> None:
        # 1. Batch-level schema-version gate. Runs before HLC parsing so a
        # stale-schema client sees the actionable error (re-fetch /schema)
        # instead of a downstream HLC complaint.
        current_version = await schema_change_log_service.current_version()
        if data.schema_version != current_version:
            raise SchemaVersionStaleError(
                expected=current_version,
                received=data.schema_version,
            )

        # One server-now read covers the whole batch so an event at the
        # edge of the drift budget cannot get re-checked against a later
        # server time mid-iteration.
        server_now_ms = wall_now_ms()
        limit_ms = int(drift_limit_seconds * 1000)

        services = EventServiceBundle(
            asset_type_field_service=asset_type_field_service,
            maintenance_record_type_field_service=maintenance_record_type_field_service,
        )

        for event in data.events:
            # 2. Per-event envelope check (HLC parse + drift bound).
            try:
                parsed = HLC.parse(event.hlc)
            except HLCParseError as exc:
                raise ValidationException(detail=str(exc)) from exc
            drift_ms = parsed.physical_ms - server_now_ms
            if drift_ms > limit_ms:
                raise HLCDriftExceededError(
                    hlc=event.hlc,
                    drift_seconds=drift_ms / 1000,
                    limit_seconds=drift_limit_seconds,
                )

            # 3. Dispatch to the (family, body_type) handler.
            await dispatch(services, request.auth, event)
