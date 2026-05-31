"""Protocol errors for the /sync/live WebSocket.

Mirrors how the HTTP side carries an :class:`ErrorCode`, but instead of
an HTTP status each error carries an RFC 6455 close code. The controller
catches :class:`SyncProtocolError`, sends a WS-flavoured problem-details
text frame, and closes the socket with ``close_code``.
"""

from __future__ import annotations

from typing import Any

from litestar.status_codes import (
    WS_1003_UNSUPPORTED_DATA,
    WS_1008_POLICY_VIOLATION,
)

from novamoc.domain._errors import _DEFAULT_MESSAGES, ErrorCode


class SyncProtocolError(Exception):
    """A WebSocket handshake/protocol violation.

    Directly instantiable for value errors that reuse an existing code
    (e.g. a negative cursor reusing ``invalid_payload_shape`` but closing
    ``1008``); subclasses fix ``code`` / ``close_code`` for the common
    cases.
    """

    def __init__(
        self,
        *,
        code: ErrorCode,
        close_code: int,
        message: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.close_code = close_code
        self.message = message or _DEFAULT_MESSAGES[code]
        self.extras = extras or {}
        super().__init__(self.message)


class TenantMismatchError(SyncProtocolError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            code=ErrorCode.TENANT_MISMATCH,
            close_code=WS_1008_POLICY_VIOLATION,
            message=message,
        )


class HandshakeTimeoutError(SyncProtocolError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            code=ErrorCode.HANDSHAKE_TIMEOUT,
            close_code=WS_1008_POLICY_VIOLATION,
            message=message,
        )


class MalformedHelloError(SyncProtocolError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            close_code=WS_1003_UNSUPPORTED_DATA,
            message=message,
        )
