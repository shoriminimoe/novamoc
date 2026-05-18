"""Wire payloads for the M5 auth endpoints.

Defines the request/response shapes for ``POST /auth/login`` and
``GET /auth/me``. ``forbid_unknown_fields=True`` on :class:`LoginRequest`
mirrors the schema-command pattern: accidental extra fields fail loud as
``400 invalid_payload_shape`` rather than being silently dropped.

:class:`MeResponse` is intentionally minimal per ADR-020 — future fields
extend the struct without breaking SPA code. :class:`MePrincipal` is the
wire shape for ``GET /auth/me`` and is intentionally distinct from
:class:`Principal` (the internal request-scope object). They share
fields today; they may not tomorrow.
"""

# Structs below are msgspec-introspected at runtime by Litestar's
# decoders/encoders; field-annotation imports stay at runtime.

from __future__ import annotations

import msgspec


class LoginRequest(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    username: str
    password: str


class MePrincipal(msgspec.Struct, frozen=True):
    id: str
    username: str


class MeTenant(msgspec.Struct, frozen=True):
    id: str
    display_name: str


class MeResponse(msgspec.Struct, frozen=True):
    user: MePrincipal
    tenant: MeTenant
