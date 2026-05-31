"""Wire frames for the /sync/live WebSocket (ADR-013).

JSON text frames tagged on ``type`` so the taxonomy can grow
(``event`` / ``ack`` / ``schema_changed``) in later milestones. M3.1
ships the three frames the handshake needs: the client's ``hello``, the
server's ``welcome``, and the ``pong`` reply to a client ``ping``.
"""

from __future__ import annotations

import uuid

import msgspec


class Hello(msgspec.Struct, forbid_unknown_fields=True, tag_field="type", tag="hello"):
    """First client frame. ``tenant_id`` is checked against the
    cookie-authenticated tenant; ``cursor`` is the last ``event_log.seq``
    the client has applied (validated ``>= 0`` by the handler)."""

    tenant_id: uuid.UUID
    cursor: int


class Welcome(msgspec.Struct, tag_field="type", tag="welcome"):
    """Server's acceptance frame carrying the tenant's current state."""

    server_seq: int
    schema_version: int


class Pong(msgspec.Struct, tag_field="type", tag="pong"):
    """Reply to a client ``ping``."""
