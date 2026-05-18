"""Wire payloads for the M5 auth endpoints.

Defines the request/response shapes for ``POST /auth/login`` and
``GET /auth/me``. ``forbid_unknown_fields=True`` on :class:`LoginRequest`
mirrors the schema-command pattern: accidental extra fields fail loud as
``400 invalid_payload_shape`` rather than being silently dropped.

``LoginRequest.password`` is :class:`msgspec_ext.SecretStr` so it masks
its value in ``repr``/``str``/logs; the underlying string is retrieved
via ``.get_secret_value()``. msgspec's decoder is strict about subclass
identity, so :func:`decode_hook` is the dec_hook the M5.10 controller
(and these payloads' tests) plug into ``msgspec.json.Decoder`` /
Litestar's ``type_decoders`` to turn JSON strings into ``SecretStr``
instances on the way in.

:class:`MeResponse` is intentionally minimal per ADR-020 — future fields
extend the struct without breaking SPA code. :class:`MePrincipal` is the
wire shape for ``GET /auth/me`` and is intentionally distinct from
:class:`Principal` (the internal request-scope object). They share
fields today; they may not tomorrow.
"""

# Structs below are msgspec-introspected at runtime by Litestar's
# decoders/encoders; field-annotation imports stay at runtime.

from __future__ import annotations

from typing import Any

import msgspec
from msgspec_ext import SecretStr


class LoginRequest(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    username: str
    password: SecretStr


class MePrincipal(msgspec.Struct, frozen=True):
    id: str
    username: str


class MeTenant(msgspec.Struct, frozen=True):
    id: str
    display_name: str


class MeResponse(msgspec.Struct, frozen=True):
    user: MePrincipal
    tenant: MeTenant


def decode_hook(typ: type, obj: Any) -> Any:
    """msgspec dec_hook for the auth payloads.

    msgspec.json.decode rejects ``str -> SecretStr`` without help because
    ``SecretStr`` is a subclass of ``str`` rather than ``str`` itself.
    Plug this into ``msgspec.json.Decoder(type=..., dec_hook=...)`` or
    Litestar's ``type_decoders``.
    """
    if typ is SecretStr and isinstance(obj, str):
        return SecretStr(obj)
    raise NotImplementedError(f"Unsupported type for decode_hook: {typ!r}")
