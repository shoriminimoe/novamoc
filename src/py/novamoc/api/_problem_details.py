"""RFC 9457 problem-details rendering for the whole API.

The `ProblemDetails` msgspec struct is published as the OpenAPI response
body for every error path. The converters below turn typed exceptions
(`SchemaError`, msgspec/Litestar validation errors, eventually
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
"""

from __future__ import annotations

import uuid

import msgspec
from litestar.exceptions import ValidationException
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.domain.schema._errors import (
    ErrorCode,
    SchemaError,
)

# TODO(#13): replace with the published docs URL once it exists. The
# leaf segment is the stable contract; the base is opaque per RFC 9457 §3.1.
_PROBLEM_TYPE_BASE = "urn:novamoc:problems"


_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
    ErrorCode.TENANT_NOT_FOUND: "Tenant not found",
}


_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.PAYLOAD_NO_CHANGES: 400,
    ErrorCode.INVALID_PAYLOAD_SHAPE: 400,
    ErrorCode.NAME_RESERVED: 409,
    ErrorCode.PARENT_TYPE_NOT_FOUND: 409,
    ErrorCode.ENTITY_NOT_FOUND: 404,
    ErrorCode.TENANT_NOT_FOUND: 404,
}


def _type_uri(code: ErrorCode) -> str:
    return f"{_PROBLEM_TYPE_BASE}:{code.value}"


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


def schema_error_to_problem_details(
    exc: SchemaError,
) -> ProblemDetailsException:
    """Convert a `SchemaError` to a `ProblemDetailsException`.

    The plugin's response renderer flattens `extra` into top-level keys
    when it is a Mapping (RFC 9457 §3.2 extension members).
    """

    return ProblemDetailsException(
        type_=_type_uri(exc.code),
        title=_TITLES[exc.code],
        status_code=_STATUS_CODES[exc.code],
        detail=exc.message,
        instance=make_instance(),
        extra=dict(exc.extras) if exc.extras else None,
    )


def _invalid_payload_shape(detail: str) -> ProblemDetailsException:
    code = ErrorCode.INVALID_PAYLOAD_SHAPE
    return ProblemDetailsException(
        type_=_type_uri(code),
        title=_TITLES[code],
        status_code=_STATUS_CODES[code],
        detail=detail,
        instance=make_instance(),
    )


def msgspec_validation_error_to_problem_details(
    exc: msgspec.ValidationError,
) -> ProblemDetailsException:
    return _invalid_payload_shape(str(exc))


def litestar_validation_error_to_problem_details(
    exc: ValidationException,
) -> ProblemDetailsException:
    return _invalid_payload_shape(exc.detail or str(exc))
