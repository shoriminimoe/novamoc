"""Unit tests for :class:`HLC` (ADR-006)."""

from __future__ import annotations

import re

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from novamoc.domain.events import _hlc
from novamoc.domain.events._hlc import HLC, HLCParseError


def test_parse_round_trips_canonical_serialization() -> None:
    s = "0001700000000000-00042-node-abc"
    parsed = HLC.parse(s)
    assert parsed == HLC(physical_ms=1_700_000_000_000, logical=42, node_id="node-abc")
    assert str(parsed) == s


def test_parse_allows_dashes_in_node_id() -> None:
    parsed = HLC.parse("0001700000000000-00000-deadbeef-0001")
    assert parsed.node_id == "deadbeef-0001"


# The canonical-form predicate the parser implements, expressed for the
# property test. Anything not matching this should round-trip a parse
# failure; anything matching it must parse.
_VALID_HLC_RE = r"\A\d{16}-\d{5}-.+\Z"  # mirrors _HLC_RE in the production module


@given(st.text())
def test_parse_rejects_anything_that_isnt_canonical(s: str) -> None:
    if re.match(_VALID_HLC_RE, s):
        # Hypothesis happened to draw a syntactically valid HLC —
        # parsing must succeed and the rejection branch does not apply.
        HLC.parse(s)
        return
    with pytest.raises(HLCParseError):
        HLC.parse(s)


@given(
    physical=st.integers(min_value=0, max_value=10**16 - 1),
    logical=st.integers(min_value=0, max_value=10**5 - 1),
    node_id=st.text(
        alphabet=st.characters(blacklist_characters="\n\r\x00"),
        min_size=1,
        max_size=32,
    ),
)
def test_parse_roundtrips_arbitrary_components(
    physical: int, logical: int, node_id: str
) -> None:
    assume("\n" not in node_id and "\r" not in node_id)
    original = HLC(physical_ms=physical, logical=logical, node_id=node_id)
    parsed = HLC.parse(str(original))
    assert parsed == original


def test_dataclass_comparison_orders_by_physical_then_logical_then_node() -> None:
    earlier = HLC(physical_ms=1, logical=0, node_id="z")
    later_physical = HLC(physical_ms=2, logical=0, node_id="a")
    assert earlier < later_physical
    assert later_physical > earlier
    assert earlier == earlier  # noqa: PLR0124  -- explicit reflexivity check


def test_logical_tiebreak() -> None:
    a = HLC(physical_ms=10, logical=0, node_id="x")
    b = HLC(physical_ms=10, logical=1, node_id="x")
    assert a < b


def test_node_id_tiebreak() -> None:
    a = HLC(physical_ms=10, logical=0, node_id="aaa")
    b = HLC(physical_ms=10, logical=0, node_id="bbb")
    assert a < b


def test_tuple_order_agrees_with_string_lex_order() -> None:
    hlcs = [
        HLC(physical_ms=1_700_000_000_000, logical=0, node_id="alpha"),
        HLC(physical_ms=1_700_000_000_000, logical=1, node_id="alpha"),
        HLC(physical_ms=1_700_000_000_001, logical=0, node_id="alpha"),
        HLC(physical_ms=9_999_999_999_999, logical=0, node_id="zeta"),
    ]
    assert sorted(hlcs) == sorted(hlcs, key=str)


def test_now_fresh_node_uses_wall_clock_and_zero_logical() -> None:
    h = HLC.now(node_id="srv")
    assert h.node_id == "srv"
    assert h.logical == 0
    assert h.physical_ms >= _hlc.wall_now_ms() - 1_000


def test_now_advances_logical_when_wall_has_not_moved(monkeypatch) -> None:
    fixed = 1_700_000_000_000
    monkeypatch.setattr(_hlc, "wall_now_ms", lambda: fixed)
    first = HLC.now(node_id="srv")
    second = HLC.now(node_id="srv", prev=first)
    assert second.physical_ms == fixed
    assert second.logical == first.logical + 1


def test_now_resets_logical_when_wall_advances(monkeypatch) -> None:
    monkeypatch.setattr(_hlc, "wall_now_ms", lambda: 2_000)
    prev = HLC(physical_ms=1_000, logical=37, node_id="srv")
    nxt = HLC.now(node_id="srv", prev=prev)
    assert nxt.physical_ms == 2_000
    assert nxt.logical == 0


def test_now_keeps_prev_physical_when_wall_moved_backward(monkeypatch) -> None:
    # NTP slew or backward jump: prev.physical_ms is ahead of current
    # wall. The local algorithm holds physical and increments logical
    # to keep the HLC monotonic.
    monkeypatch.setattr(_hlc, "wall_now_ms", lambda: 500)
    prev = HLC(physical_ms=1_000, logical=5, node_id="srv")
    nxt = HLC.now(node_id="srv", prev=prev)
    assert nxt.physical_ms == 1_000
    assert nxt.logical == 6


def test_now_overflow_raises(monkeypatch) -> None:
    monkeypatch.setattr(_hlc, "wall_now_ms", lambda: 1_000)
    saturated = HLC(physical_ms=1_000, logical=_hlc.LOGICAL_MAX, node_id="srv")
    with pytest.raises(OverflowError):
        HLC.now(node_id="srv", prev=saturated)


def test_wall_now_ms_matches_time_ns(monkeypatch) -> None:
    # Property: wall_now_ms() == time.time_ns() // 1_000_000 (i.e. no
    # float intermediate). Confirm by monkeypatching time_ns to a known
    # value and reading wall_now_ms.
    monkeypatch.setattr(_hlc.time, "time_ns", lambda: 1_700_000_000_123_456_789)
    assert _hlc.wall_now_ms() == 1_700_000_000_123
