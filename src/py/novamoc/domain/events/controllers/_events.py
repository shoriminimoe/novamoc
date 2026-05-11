"""HTTP controller for ``/events`` (ADR-013).

M1.2 adds HLC parse + drift-bound validation. Each event's ``hlc``
is parsed into a structured :class:`HLC`; an HLC whose physical
component sits more than ``AppSettings.hlc_drift_limit_seconds``
ahead of the server's wall clock is rejected at acceptance time as
``hlc_drift_exceeded``. Drift is one-sided per ADR-006 — past HLCs
are always accepted; only the future side carries the honesty risk
for forged client timestamps.

Persistence, projection writes, and schema-version gating land in
M1.3+; this controller currently returns ``202 Accepted`` for every
event that survives parsing and the drift check.
"""

from __future__ import annotations

from litestar import Controller, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.domain.events import _payloads
from novamoc.domain.events._errors import HLCDriftExceededError
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = {  # noqa: RUF012
        "drift_limit_seconds": Provide(_provide_drift_limit_seconds),
    }

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(
        self,
        data: _payloads.EventBatch,
        drift_limit_seconds: float,
    ) -> None:
        # One server-now read covers the whole batch so an event at
        # the edge of the budget can't get re-checked against a later
        # server time mid-iteration.
        server_now_ms = wall_now_ms()
        limit_ms = int(drift_limit_seconds * 1000)

        for event in data.events:
            try:
                parsed = HLC.parse(event.hlc)
            except HLCParseError as exc:
                # Reaches the invalid_payload_shape converter — same
                # shape as any other malformed body.
                raise ValidationException(detail=str(exc)) from exc

            drift_ms = parsed.physical_ms - server_now_ms
            if drift_ms > limit_ms:
                raise HLCDriftExceededError(
                    hlc=event.hlc,
                    drift_seconds=drift_ms / 1000,
                    limit_seconds=drift_limit_seconds,
                )
