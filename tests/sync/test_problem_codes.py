from __future__ import annotations

from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.api._problem_details import _TITLES
from novamoc.domain._errors import ErrorCode


def test_ws_codes_registered() -> None:
    assert ErrorCode.TENANT_MISMATCH.value == "tenant_mismatch"
    assert ErrorCode.HANDSHAKE_TIMEOUT.value == "handshake_timeout"
    assert "tenant_mismatch" in PROBLEM_CODES
    assert "handshake_timeout" in PROBLEM_CODES


def test_ws_codes_have_titles() -> None:
    assert _TITLES[ErrorCode.TENANT_MISMATCH] == "Tenant mismatch"
    assert _TITLES[ErrorCode.HANDSHAKE_TIMEOUT] == "Handshake timeout"
