"""Wire frames for the /sync/live WebSocket (ADR-013).

JSON text frames tagged on ``type`` so the message taxonomy can grow
without ambiguity.
"""

from __future__ import annotations

import uuid

import msgspec


class Hello(msgspec.Struct, forbid_unknown_fields=True, tag_field="type", tag="hello"):
    """First client frame. ``tenant_id`` is checked against the
    cookie-authenticated tenant; ``cursor`` is the last ``event_log.seq``
    the client has applied."""

    tenant_id: uuid.UUID
    cursor: int


class Welcome(msgspec.Struct, tag_field="type", tag="welcome"):
    """Server's acceptance frame carrying the tenant's current state."""

    server_seq: int
    schema_version: int


class Pong(msgspec.Struct, tag_field="type", tag="pong"):
    """Reply to a client ``ping``."""
