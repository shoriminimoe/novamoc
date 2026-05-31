from __future__ import annotations

from litestar.status_codes import (
    WS_1003_UNSUPPORTED_DATA,
    WS_1008_POLICY_VIOLATION,
)

from novamoc.api._problem_details import make_ws_problem_body
from novamoc.domain._errors import ErrorCode
from novamoc.domain.sync._errors import (
    HandshakeTimeoutError,
    MalformedHelloError,
    SyncProtocolError,
    TenantMismatchError,
)


def test_tenant_mismatch_carries_code_and_close() -> None:
    exc = TenantMismatchError()
    assert exc.code is ErrorCode.TENANT_MISMATCH
    assert exc.close_code == WS_1008_POLICY_VIOLATION


def test_handshake_timeout_carries_code_and_close() -> None:
    exc = HandshakeTimeoutError()
    assert exc.code is ErrorCode.HANDSHAKE_TIMEOUT
    assert exc.close_code == WS_1008_POLICY_VIOLATION


def test_malformed_hello_is_1003() -> None:
    exc = MalformedHelloError("bad json")
    assert exc.code is ErrorCode.INVALID_PAYLOAD_SHAPE
    assert exc.close_code == WS_1003_UNSUPPORTED_DATA
    assert exc.message == "bad json"


def test_base_can_be_constructed_directly() -> None:
    exc = SyncProtocolError(
        code=ErrorCode.INVALID_PAYLOAD_SHAPE,
        close_code=WS_1008_POLICY_VIOLATION,
        message="cursor must be >= 0",
    )
    assert exc.close_code == WS_1008_POLICY_VIOLATION


def test_make_ws_problem_body_shape() -> None:
    body = make_ws_problem_body(
        code=ErrorCode.TENANT_MISMATCH,
        close_code=WS_1008_POLICY_VIOLATION,
        detail="nope",
        base_url="http://test",
    )
    assert body["type"] == "http://test/problems/tenant_mismatch.html"
    assert body["title"] == "Tenant mismatch"
    assert body["detail"] == "nope"
    assert body["ws_close_code"] == WS_1008_POLICY_VIOLATION
    assert body["instance"].startswith("urn:uuid:")
    assert "status" not in body
