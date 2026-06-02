"""Subscriber registry seam (ADR-013 fan-out scoping).

A narrow ``publish`` / ``subscribe`` / ``unsubscribe`` surface, kept
transport-mechanical (it fans out opaque pre-encoded ``bytes``) so the
backing store can be swapped — e.g. for Redis pub/sub in a multi-process
deployment — without touching the controller.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from litestar.exceptions import WebSocketException

if TYPE_CHECKING:
    import uuid

    from litestar import WebSocket


# ``runtime_checkable`` is load-bearing: Litestar isinstance-checks the
# DI-injected ``registry`` against this Protocol, which raises without it.
@runtime_checkable
class SubscriberRegistry(Protocol):
    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...

    async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None: ...


class InMemorySubscriberRegistry:
    """Per-process tenant → connected-sockets map (ADR-013 fan-out scoping).

    Single event loop: subscribe/unsubscribe mutate without awaiting, so
    they are atomic relative to publish; publish snapshots the set before
    awaiting any send.
    """

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[WebSocket]] = {}

    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        self._subscribers.setdefault(tenant_id, set()).add(socket)

    async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        subscribers = self._subscribers.get(tenant_id)
        if subscribers is None:
            return
        subscribers.discard(socket)
        if not subscribers:
            del self._subscribers[tenant_id]

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        for socket in list(self._subscribers.get(tenant_id, ())):
            # Best-effort: a closed peer must not abort fan-out to the rest;
            # its own handler's unsubscribe removes it.
            with contextlib.suppress(WebSocketException, RuntimeError):
                await socket.send_data(message, mode="text")


class NoopSubscriberRegistry:
    """No-op placeholder until the real registry is implemented."""

    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        return
