"""Shared dataclasses produced by every ratchet checker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricChange:
    """A single metric's old and new values.

    The ``metric`` label is checker-specific:
    - Ruff: rule code, e.g. ``"PLR0913"``. Values are ``int`` counts.
    - Coverage: dotted metric path, e.g. ``"python.line"``. Values are
      ``float`` percentages.
    """

    metric: str
    old: float
    new: float


@dataclass(frozen=True, slots=True)
class RatchetResult:
    """Outcome of one independent ratchet checker.

    ``regressions`` and ``improvements`` are mutually-disjoint slices of
    the same diff. ``setup_error``, when set, means the checker could not
    run (e.g. missing input artifact); other checkers in the orchestrator
    still run.
    """

    name: str
    regressions: tuple[MetricChange, ...]
    improvements: tuple[MetricChange, ...]
    setup_error: str | None = None

    @property
    def has_failure(self) -> bool:
        return bool(self.regressions or self.improvements)
