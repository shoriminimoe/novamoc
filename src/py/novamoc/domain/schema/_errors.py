"""Typed exceptions raised by schema endpoints (commands and reads).

Each exception carries an ``ErrorCode`` (the stable failure-mode
identifier), an optional human-readable message, and a free-form
mapping of extras for per-failure context (e.g., the conflicting
name on a name-collision). Subclasses categorize failures; handlers
raise the most specific one that fits.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    PAYLOAD_NO_CHANGES = "payload_no_changes"
    INVALID_PAYLOAD_SHAPE = "invalid_payload_shape"
    NAME_RESERVED = "name_reserved"
    PARENT_TYPE_NOT_FOUND = "parent_type_not_found"
    ENTITY_NOT_FOUND = "entity_not_found"
    TENANT_NOT_FOUND = "tenant_not_found"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Request payload did not match the expected shape.",
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
    ErrorCode.TENANT_NOT_FOUND: "Tenant not found.",
}


class SchemaError(Exception):
    """Base class for schema endpoint failures (command and read alike)."""

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


class PayloadShapeError(SchemaError):
    """Request payload was well-formed but did not match the command's
    expectations (missing required fields, empty update, ...)."""


class ConflictError(SchemaError):
    """Request conflicted with the current projection state (name
    already taken, parent type missing, ...)."""


class EntityNotFoundError(SchemaError):
    """Command targeted an entity that does not exist."""


class TenantNotFoundError(SchemaError):
    """Request targeted a tenant that the server does not know about."""
