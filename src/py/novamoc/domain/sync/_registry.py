"""Subscriber registry seam (ADR-013 fan-out scoping).

M3.1 ships the interface and a no-op implementation so the handshake
path can call ``subscribe`` / ``unsubscribe`` before the real in-memory
map lands in #37. The Protocol is the narrow ``publish`` / ``subscribe``
/ ``unsubscribe`` surface #37 asks for, kept transport-mechanical (the
registry fans out opaque pre-encoded ``bytes``) so a future deployment
can swap a Redis-backed store without touching the controller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import uuid

    from litestar import WebSocket


@runtime_checkable
class SubscriberRegistry(Protocol):
    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...

    async def unsubscribe(
        self, tenant_id: uuid.UUID, socket: WebSocket
    ) -> None: ...

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None: ...


class NoopSubscriberRegistry:
    """Placeholder until the real registry lands (#37). All methods are
    no-ops so the handshake path is exercisable now."""

    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def unsubscribe(
        self, tenant_id: uuid.UUID, socket: WebSocket
    ) -> None:
        return

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        return
