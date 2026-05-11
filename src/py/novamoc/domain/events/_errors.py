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
