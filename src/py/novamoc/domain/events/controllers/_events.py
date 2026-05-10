"""HTTP controller for ``/events`` (ADR-013).

M1.1 scaffold: accept a valid :class:`EventBatch` and return
``202 Accepted``. Validation, persistence, and projection writes land
in M1.2+. Autocommit is configured globally on the SQLAlchemy plugin.
"""

from __future__ import annotations

from litestar import Controller, post
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.domain.events import _payloads


class EventsController(Controller):
    path = "/events"
    tags = ("events",)

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(self, data: _payloads.EventBatch) -> None:
        # `data` is decoded by Litestar to exercise wire validation; the
        # scaffold endpoint does not act on it yet.
        return None
