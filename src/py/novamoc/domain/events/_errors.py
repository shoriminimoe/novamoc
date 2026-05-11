"""Typed exceptions raised by the events endpoint."""

from __future__ import annotations

from novamoc.domain._errors import DomainError, ErrorCode


class HLCDriftExceededError(DomainError):
    """Event HLC sits more than the configured drift bound ahead of
    the server's wall clock (ADR-006)."""

    def __init__(
        self,
        *,
        hlc: str,
        drift_seconds: float,
        limit_seconds: float,
    ) -> None:
        super().__init__(
            code=ErrorCode.HLC_DRIFT_EXCEEDED,
            hlc=hlc,
            drift_seconds=drift_seconds,
            limit_seconds=limit_seconds,
        )


class SchemaVersionStaleError(DomainError):
    """Batch's ``schema_version`` does not match the tenant's current
    schema version (ADR-008 / ADR-009).

    Schema upgrades are mandatory: events generated against a stale
    schema cannot be safely folded into a projection that has since
    evolved, so the server refuses them and the client must re-fetch
    the schema before retrying.
    """

    def __init__(self, *, expected: int, received: int) -> None:
        super().__init__(
            code=ErrorCode.SCHEMA_VERSION_STALE,
            expected=expected,
            received=received,
        )


class UnknownFieldError(DomainError):
    """Event references a field that does not exist on the targeted
    entity type (ADR-008 / ADR-012).

    Tombstoned (``active=false``) fields are *not* rejected here —
    ADR-012 decouples the data fold from schema visibility so events
    can still land on a field that has been deactivated. This error
    fires when the field id (or ``col:<name>`` column) is not present
    on the entity type at all.
    """

    def __init__(
        self,
        *,
        family: str,
        type_id: str,
        field: str,
    ) -> None:
        super().__init__(
            code=ErrorCode.UNKNOWN_FIELD,
            family=family,
            type_id=type_id,
            field=field,
        )


class ValueTypeMismatchError(DomainError):
    """Event value's JSON shape does not match the field's declared
    :class:`FieldDataType` (ADR-005)."""

    def __init__(
        self,
        *,
        field: str,
        expected: str,
        received: str,
    ) -> None:
        super().__init__(
            code=ErrorCode.VALUE_TYPE_MISMATCH,
            field=field,
            expected=expected,
            received=received,
        )
