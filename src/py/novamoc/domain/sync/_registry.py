"""Subscriber registry seam (ADR-013 fan-out scoping).

A narrow ``publish`` / ``subscribe`` / ``unsubscribe`` surface, kept
transport-mechanical (it fans out opaque pre-encoded ``bytes``) so the
backing store can be swapped — e.g. for Redis pub/sub in a multi-process
deployment — without touching the controller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

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


class NoopSubscriberRegistry:
    """No-op placeholder until the real registry is implemented."""

    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        return
