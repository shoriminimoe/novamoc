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
