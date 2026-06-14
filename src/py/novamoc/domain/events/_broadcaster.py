"""Background fan-out broadcaster (ADR-013).

Tails ``event_log`` and publishes each new row to the per-tenant
:class:`SubscriberRegistry`. Decoupled from the request lifecycle: the
accept path only fires a non-blocking signal post-commit; all DB reads,
encoding, and per-socket sends happen here. Reads only committed rows, so
a rolled-back batch is never fanned out.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import msgspec

from novamoc.domain.events._pagination import _row_to_recorded_event
from novamoc.domain.events.services import EventLogService

if TYPE_CHECKING:
    from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

    from novamoc.domain.sync._registry import SubscriberRegistry

_logger = logging.getLogger(__name__)


class EventBroadcaster:
    def __init__(
        self,
        registry: SubscriberRegistry,
        alchemy_config: SQLAlchemyAsyncConfig,
        *,
        batch_size: int,
    ) -> None:
        self._registry = registry
        self._alchemy_config = alchemy_config
        self._batch_size = batch_size
        self._last_seq = 0
        self._wake = asyncio.Event()

    async def start_at_tip(self) -> None:
        """Set the cursor to the current global tip so a restart does not
        replay history. Returning clients catch up over HTTP and then connect
        for the live tail from here (ADR-013)."""
        async with self._alchemy_config.get_session() as session:
            self._last_seq = await EventLogService(
                session=session
            ).current_seq_all_tenants()

    async def drain_once(self) -> int:
        async with self._alchemy_config.get_session() as session:
            rows = await EventLogService(session=session).list_after_all_tenants(
                self._last_seq, self._batch_size
            )
        for row in rows:
            payload = msgspec.json.encode(_row_to_recorded_event(row))
            await self._registry.publish(row.tenant_id, payload)
            # Advance only after a successful publish: a transient failure
            # leaves _last_seq behind this row, so run()'s except retries it
            # from here on the next signal. (Rows are validated at accept, so
            # there is no persistent-encode-failure case to skip past.)
            self._last_seq = row.seq
        return len(rows)

    def notify(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()  # clear BEFORE draining: a notify mid-drain re-wakes us
            try:
                while await self.drain_once():
                    pass
            except Exception:
                _logger.exception("Transient error in broadcaster drain; continuing")
