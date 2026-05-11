"""HTTP controller for ``/events`` (ADR-013).

The handler enforces two pre-persistence gates before the batch is
accepted:

* Schema-version gate (M1.3, ADR-008 / ADR-009): the batch's
  ``schema_version`` must equal the tenant's current schema
  version. A mismatch is rejected as ``schema_version_stale`` (409)
  so the projection fold never sees events authored against a
  schema the server has since evolved past.
* HLC validation (M1.2, ADR-006): each event's ``hlc`` is parsed
  into a structured :class:`HLC`; an HLC whose physical component
  sits more than ``AppSettings.hlc_drift_limit_seconds`` ahead of
  the server's wall clock is rejected as ``hlc_drift_exceeded``.
  Past HLCs are always accepted — drift is one-sided.

Persistence and projection writes land in M1.5+; this controller
currently returns ``202 Accepted`` for every batch that survives
both gates.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.domain.events import _payloads
from novamoc.domain.events._errors import (
    HLCDriftExceededError,
    SchemaVersionStaleError,
)
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms
from novamoc.domain.schema.services import SchemaChangeLogService


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = {
        "drift_limit_seconds": Provide(_provide_drift_limit_seconds)
    } | providers.create_service_dependencies(
        SchemaChangeLogService, "schema_change_log_service"
    )

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(
        self,
        data: _payloads.EventBatch,
        drift_limit_seconds: float,
        schema_change_log_service: SchemaChangeLogService,
    ) -> None:
        # Schema-version gate runs before HLC parsing so a stale-
        # schema client gets the actionable error (re-fetch /schema)
        # instead of a secondary HLC complaint.
        current_version = await schema_change_log_service.current_version()
        if data.schema_version != current_version:
            raise SchemaVersionStaleError(
                expected=current_version,
                received=data.schema_version,
            )

        # One server-now read covers the whole batch so an event at
        # the edge of the budget isn't re-checked mid-iteration.
        server_now_ms = wall_now_ms()
        limit_ms = int(drift_limit_seconds * 1000)

        for event in data.events:
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
