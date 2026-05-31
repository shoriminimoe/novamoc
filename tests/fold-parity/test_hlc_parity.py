"""Cross-language parity for the client HLC string format (ADR-006).

The client (``src/js/web/src/lib/db/hlc.ts``) and the server
(``novamoc.domain.events._hlc``) serialize HLCs identically so the two
streams interleave under one ``TEXT`` ordering. This test loads a fixture of
client-produced HLC strings and asserts the *server's real parser* accepts
each and recovers the same components — guarding against the two formats
drifting apart.

Self-contained by design: pytest auto-discovers it (``testpaths=["tests"]``)
with no extra wiring and no dependency on a fold-parity runner or conftest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novamoc.domain.events._hlc import HLC

_FIXTURE = Path(__file__).parent / "hlc_basic.json"
_CASES = json.loads(_FIXTURE.read_text())["hlcs"]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["hlc"])
def test_server_parser_accepts_client_hlc(case: dict[str, object]) -> None:
    hlc_str = str(case["hlc"])
    parsed = HLC.parse(hlc_str)

    assert parsed.physical_ms == case["physical_ms"]
    assert parsed.logical == case["logical"]
    assert parsed.node_id == case["node_id"]
    # Round-trips back to the exact client string.
    assert str(parsed) == hlc_str
