"""Hybrid Logical Clock value type and helpers (ADR-006).

An :class:`HLC` is the triple ``(physical_ms, logical, node_id)``
serialized as ``{physical_ms:016}-{logical:05}-{node_id}``. Fixed-
width zero-padding makes lexicographic string comparison agree with
component-wise numeric comparison — the property the SQL fold relies
on. The dataclass is ``order=True`` so callers compare with
``<`` / ``>`` directly; no separate ``compare`` helper.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Final

PHYSICAL_WIDTH: Final = 16
LOGICAL_WIDTH: Final = 5
LOGICAL_MAX: Final = 10**LOGICAL_WIDTH - 1

# Two numeric components by fixed width, then anything non-empty as
# the node_id. ADR-006 leaves the node_id encoding opaque.
_HLC_RE: Final = re.compile(
    rf"\A(\d{{{PHYSICAL_WIDTH}}})-(\d{{{LOGICAL_WIDTH}}})-(.+)\Z"
)


class HLCParseError(ValueError):
    """Raised when an HLC string does not match the canonical format."""


def wall_now_ms() -> int:
    """Server wall clock in HLC physical-component units (epoch ms).

    Uses :func:`time.time_ns` so the conversion does not lose
    sub-microsecond precision the way ``int(time.time() * 1000)`` can
    around the float64 epoch-millisecond range.
    """
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True, order=True)
class HLC:
    """One Hybrid Logical Clock timestamp.

    Field ordering ``(physical_ms, logical, node_id)`` matches the
    lex order of :meth:`__str__`, so ``a < b`` agrees with
    ``str(a) < str(b)``.

    Attributes:
        physical_ms: Epoch milliseconds.
        logical: Tiebreaker counter within a single ms tick.
        node_id: Opaque per-device identifier.
    """

    physical_ms: int
    logical: int
    node_id: str

    def __str__(self) -> str:
        return (
            f"{self.physical_ms:0{PHYSICAL_WIDTH}d}"
            f"-{self.logical:0{LOGICAL_WIDTH}d}"
            f"-{self.node_id}"
        )

    @classmethod
    def parse(cls, s: str) -> HLC:
        """Parse the canonical serialized form.

        Raises:
            HLCParseError: ``s`` does not match
                ``{physical:016}-{logical:05}-{node_id}``.
        """
        m = _HLC_RE.match(s)
        if m is None:
            msg = f"invalid HLC: {s!r}"
            raise HLCParseError(msg)
        return cls(physical_ms=int(m[1]), logical=int(m[2]), node_id=m[3])

    @classmethod
    def now(cls, *, node_id: str, prev: HLC | None = None) -> HLC:
        """Stamp a new HLC for a server-generated event.

        Implements the ADR-006 local-event algorithm: when wall time
        has moved past ``prev.physical_ms``, reset ``logical`` to
        zero; otherwise tick the logical counter.

        Raises:
            OverflowError: ``prev.logical`` is already
                :data:`LOGICAL_MAX` within the same wall millisecond.
        """
        wall = wall_now_ms()
        if prev is None or wall > prev.physical_ms:
            return cls(physical_ms=wall, logical=0, node_id=node_id)
        if prev.logical >= LOGICAL_MAX:
            msg = f"HLC logical counter overflow at physical_ms={prev.physical_ms}"
            raise OverflowError(msg)
        return cls(
            physical_ms=prev.physical_ms,
            logical=prev.logical + 1,
            node_id=node_id,
        )
