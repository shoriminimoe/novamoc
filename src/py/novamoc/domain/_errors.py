"""Shared base for typed domain exceptions that render as RFC 9457.

Every domain failure raises a :class:`DomainError` (or subclass)
carrying an :class:`ErrorCode`, a human-readable message, and a
free-form ``extras`` dict that lands in the problem-details
response as extension members. Subclasses categorize failures so
the converter in ``api._problem_details`` can dispatch on type.
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
    HLC_DRIFT_EXCEEDED = "hlc_drift_exceeded"
    SCHEMA_VERSION_STALE = "schema_version_stale"
    UNKNOWN_FIELD = "unknown_field"
    VALUE_TYPE_MISMATCH = "value_type_mismatch"
    LOGIN_FAILED = "login_failed"
    USER_ALREADY_HAS_TENANT = "user_already_has_tenant"
    TENANT_MISMATCH = "tenant_mismatch"
    HANDSHAKE_TIMEOUT = "handshake_timeout"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: (
        "Request payload did not match the expected shape."
    ),
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
    ErrorCode.HLC_DRIFT_EXCEEDED: (
        "Event HLC physical clock is too far ahead of the server's wall clock."
    ),
    ErrorCode.SCHEMA_VERSION_STALE: (
        "Batch schema_version does not match the tenant's current schema version."
    ),
    ErrorCode.UNKNOWN_FIELD: (
        "Event references a field that does not exist on this entity type."
    ),
    ErrorCode.VALUE_TYPE_MISMATCH: (
        "Event value's JSON shape does not match the field's declared data type."
    ),
    # Anti-enumeration: deliberately does not mention "password" or
    # "username". Wrong password, unknown user, disabled user, and the
    # 0-membership transient all share this body byte-for-byte.
    ErrorCode.LOGIN_FAILED: "The provided credentials were not accepted.",
    ErrorCode.USER_ALREADY_HAS_TENANT: (
        "This user already belongs to a tenant. v1 supports only one "
        "tenant per user; switching active tenant is not yet available."
    ),
    ErrorCode.TENANT_MISMATCH: (
        "The hello frame's tenant_id does not match the authenticated tenant."
    ),
    ErrorCode.HANDSHAKE_TIMEOUT: (
        "No hello frame was received within the handshake window."
    ),
}


class DomainError(Exception):
    """Base for problem-details-shaped domain failures."""

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


class PayloadShapeError(DomainError):
    """Wire-decoded payload did not match the command's expectations."""


class ConflictError(DomainError):
    """Request conflicted with the current projection state."""


class EntityNotFoundError(DomainError):
    """Targeted entity does not exist."""
