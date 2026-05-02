"""Typed exceptions raised by schema-command handlers.

A single Litestar exception handler renders any ``SchemaCommandError`` as
the JSON envelope documented in the spec; ``msgspec.ValidationError`` is
mapped separately at the controller layer to the same shape with
``code=invalid_payload_shape``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # 400 — invalid_request (request shape)
    PAYLOAD_NO_CHANGES = "payload_no_changes"
    INVALID_PAYLOAD_SHAPE = "invalid_payload_shape"
    # 409 — conflict (request well-shaped, conflicts with current projection state)
    NAME_RESERVED = "name_reserved"
    PARENT_TYPE_NOT_FOUND = "parent_type_not_found"
    # 404 — not_found
    ENTITY_NOT_FOUND = "entity_not_found"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Request payload did not match the expected shape.",
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
}


class SchemaCommandError(Exception):
    """Base class for schema-command failures.

    Subclasses pin ``status_code`` and the ``error`` label that appear in
    the response envelope. The ``code`` discriminates failure modes within
    a category and is what clients branch on.
    """

    status_code: int = 400
    error: str = "invalid_request"

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str | None = None,
        **extras: Any,
    ) -> None:
        super().__init__(message or _DEFAULT_MESSAGES[code])
        self.code = code
        self.message = message or _DEFAULT_MESSAGES[code]
        self.extras = extras


class PayloadShapeError(SchemaCommandError):
    status_code = 400
    error = "invalid_request"


class ConflictError(SchemaCommandError):
    status_code = 409
    error = "conflict"


class EntityNotFoundError(SchemaCommandError):
    status_code = 404
    error = "not_found"
