"""RFC 9457 problem-details rendering for the whole API.

The `ProblemDetails` msgspec struct is published as the OpenAPI response
body for every error path. The converters below turn typed exceptions
(`DomainError`, msgspec/Litestar validation errors, eventually
others) into Litestar's `ProblemDetailsException`, which the
`ProblemDetailsPlugin` renders as `application/problem+json`.

Wire shape:
- `type` — opaque URI; clients branch on its leaf segment (the code).
- `title` — short, fixed string per code.
- `status` — HTTP status code, also on the response line.
- `detail` — human-readable message; not stable, do not branch on it.
- `instance` — `urn:uuid:<uuid4>` per occurrence, for log correlation.

Per-error-code extras (e.g., the conflicting `name`) are RFC 9457 §3.2
extension members — top-level keys alongside the standard slots.

Each converter is built by a `make_*_converter(base_url)` factory that
closes over the configured docs base URL. ``create_app`` constructs
them once at startup with ``Settings.app.docs_base_url`` and
registers them on the `ProblemDetailsPlugin`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import msgspec
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.domain._errors import (
    ErrorCode,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.exceptions import ValidationException

    from novamoc.domain._errors import DomainError
    from novamoc.domain.accounts import TenantResolutionError

_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
    ErrorCode.HLC_DRIFT_EXCEEDED: "HLC drift exceeded",
    ErrorCode.SCHEMA_VERSION_STALE: "Schema version stale",
    ErrorCode.UNKNOWN_FIELD: "Unknown field",
    ErrorCode.VALUE_TYPE_MISMATCH: "Value type mismatch",
    ErrorCode.LOGIN_FAILED: "Login failed",
    ErrorCode.USER_ALREADY_HAS_TENANT: "User already has a tenant",
    ErrorCode.TENANT_MISMATCH: "Tenant mismatch",
    ErrorCode.HANDSHAKE_TIMEOUT: "Handshake timeout",
}


_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.PAYLOAD_NO_CHANGES: 400,
    ErrorCode.INVALID_PAYLOAD_SHAPE: 400,
    ErrorCode.NAME_RESERVED: 409,
    ErrorCode.PARENT_TYPE_NOT_FOUND: 409,
    ErrorCode.ENTITY_NOT_FOUND: 404,
    ErrorCode.HLC_DRIFT_EXCEEDED: 400,
    ErrorCode.SCHEMA_VERSION_STALE: 409,
    ErrorCode.UNKNOWN_FIELD: 404,
    ErrorCode.VALUE_TYPE_MISMATCH: 400,
    ErrorCode.LOGIN_FAILED: 401,
    ErrorCode.USER_ALREADY_HAS_TENANT: 409,
}


def _type_uri(code: ErrorCode | str, base_url: str) -> str:
    # The ``.html`` suffix is part of the URL path, not the code; clients
    # that branch on the leaf segment strip the extension to recover the
    # code. See ADR-018.
    code_str = code.value if isinstance(code, ErrorCode) else code
    return f"{base_url}/problems/{code_str}.html"


class ProblemDetails(msgspec.Struct, omit_defaults=True):
    """OpenAPI body schema for an `application/problem+json` response.

    Documentation-only: this struct is never instantiated at runtime.
    It exists so controllers can reference it from `ResponseSpec(...)`
    and clients generated from the OpenAPI document see typed fields
    (`type`, `title`, `status`, `detail`, `instance`) instead of the
    generic shape Litestar would otherwise emit for
    `ProblemDetailsException`. Per-error extension members (RFC 9457
    §3.2) are not declared here — they ride through `ProblemDetailsException.extra`
    at runtime and consumers ignore unknown fields.
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str


def make_instance() -> str:
    """Return an opaque per-occurrence instance identifier (`urn:uuid:<uuid4>`)."""

    return f"urn:uuid:{uuid.uuid4()}"


def make_problem_body(exc: DomainError, base_url: str) -> dict[str, Any]:
    """RFC 9457 problem-details body for ``exc``.

    The dict matches the JSON shape an ``application/problem+json``
    response would carry: standard slots first (``type``, ``title``,
    ``status``, ``detail``, ``instance``), then per-error extras as
    top-level extension members per RFC 9457 §3.2.

    Callers in the events endpoint embed this dict under
    ``EventOutcome.problem`` so a rejected per-event outcome carries
    the same diagnostic surface a batch-level error response would.
    """
    body: dict[str, Any] = {
        "type": _type_uri(exc.code, base_url),
        "title": _TITLES[exc.code],
        "status": _STATUS_CODES[exc.code],
        "detail": exc.message,
        "instance": make_instance(),
    }
    if exc.extras:
        body.update(exc.extras)
    return body


def make_domain_error_converter(
    base_url: str,
) -> Callable[[DomainError], ProblemDetailsException]:
    def _convert(exc: DomainError) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri(exc.code, base_url),
            title=_TITLES[exc.code],
            status_code=_STATUS_CODES[exc.code],
            detail=exc.message,
            instance=make_instance(),
            extra=dict(exc.extras) if exc.extras else None,
        )

    return _convert


def make_tenant_resolution_error_converter(
    base_url: str,
) -> Callable[[TenantResolutionError], ProblemDetailsException]:
    def _convert(exc: TenantResolutionError) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri("tenant_not_resolved", base_url),
            title="Tenant not resolved",
            status_code=401,
            detail=exc.detail,
            instance=make_instance(),
        )

    return _convert


def _make_invalid_payload_shape(
    base_url: str,
) -> Callable[[str], ProblemDetailsException]:
    code = ErrorCode.INVALID_PAYLOAD_SHAPE

    def _build(detail: str) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri(code, base_url),
            title=_TITLES[code],
            status_code=_STATUS_CODES[code],
            detail=detail,
            instance=make_instance(),
        )

    return _build


def make_msgspec_validation_error_converter(
    base_url: str,
) -> Callable[[msgspec.ValidationError], ProblemDetailsException]:
    build = _make_invalid_payload_shape(base_url)

    def _convert(exc: msgspec.ValidationError) -> ProblemDetailsException:
        return build(str(exc))

    return _convert


def make_litestar_validation_error_converter(
    base_url: str,
) -> Callable[[ValidationException], ProblemDetailsException]:
    build = _make_invalid_payload_shape(base_url)

    def _convert(exc: ValidationException) -> ProblemDetailsException:
        return build(exc.detail or str(exc))

    return _convert
