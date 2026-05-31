"""WebSocket controller for /sync/live (ADR-013, M3.1).

Cookie-authenticated upgrade (the middleware stack populates
``socket.auth`` on WS scope), a ``hello`` → ``welcome`` handshake, then
register the connection against the subscriber registry and idle. The
idle loop answers ``ping`` with ``pong`` and ignores every other frame —
client→server event push and ``schema_changed`` are later-milestone
concerns. Protocol errors send a WS-flavoured problem-details frame and
close with an RFC 6455 code.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import msgspec
from advanced_alchemy.extensions.litestar import providers
from litestar import (  # noqa: TC002  # handler param type, resolved at runtime by Litestar
    Controller,
    WebSocket,
    websocket,
)
from litestar.datastructures import State  # noqa: TC002  # runtime DI provider
from litestar.di import Provide
from litestar.exceptions import (
    SerializationException,
    WebSocketDisconnect,
    WebSocketException,
)
from litestar.status_codes import WS_1008_POLICY_VIOLATION

from novamoc.api._problem_details import make_ws_problem_body
from novamoc.domain._errors import ErrorCode
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._errors import (
    HandshakeTimeoutError,
    MalformedHelloError,
    SyncProtocolError,
    TenantMismatchError,
)
from novamoc.domain.sync._payloads import Hello, Pong, Welcome
from novamoc.domain.sync._registry import (
    SubscriberRegistry,  # noqa: TC001  # runtime DI return annotation and handler param type
)

if TYPE_CHECKING:
    import uuid


async def _provide_registry(state: State) -> SubscriberRegistry:
    return state.subscriber_registry


async def _provide_handshake_timeout(state: State) -> float:
    return state.settings.app.ws_handshake_timeout_seconds


async def _provide_docs_base_url(state: State) -> str:
    return state.settings.app.docs_base_url


async def _read_hello(socket: WebSocket, timeout_seconds: float) -> Hello:
    try:
        async with asyncio.timeout(timeout_seconds):
            raw = await socket.receive_text()
    except TimeoutError as exc:
        raise HandshakeTimeoutError from exc
    try:
        return msgspec.json.decode(raw, type=Hello)
    except msgspec.MsgspecError as exc:
        raise MalformedHelloError(str(exc)) from exc


def _validate_hello(hello: Hello, auth_tenant_id: uuid.UUID) -> None:
    if hello.tenant_id != auth_tenant_id:
        raise TenantMismatchError
    if hello.cursor < 0:
        raise SyncProtocolError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            close_code=WS_1008_POLICY_VIOLATION,
            message="cursor must be >= 0",
        )


async def _close_with_problem(
    socket: WebSocket, exc: SyncProtocolError, docs_base_url: str
) -> None:
    body = make_ws_problem_body(
        code=exc.code,
        close_code=exc.close_code,
        detail=exc.message,
        base_url=docs_base_url,
        extras=exc.extras,
    )
    # Best-effort: a half-closed socket must not mask the protocol error.
    with contextlib.suppress(WebSocketException, RuntimeError):
        await socket.send_json(body)
    await socket.close(code=exc.close_code, reason=exc.code.value)


async def _idle_loop(socket: WebSocket) -> None:
    while True:
        try:
            frame = await socket.receive_json()
        except WebSocketDisconnect:
            return
        except SerializationException:
            continue
        if isinstance(frame, dict) and frame.get("type") == "ping":
            await socket.send_json(Pong())


class SyncController(Controller):
    path = "/sync/live"
    tags = ("sync",)
    dependencies = (
        {
            "registry": Provide(_provide_registry),
            "handshake_timeout": Provide(_provide_handshake_timeout),
            "docs_base_url": Provide(_provide_docs_base_url),
        }
        | providers.create_service_dependencies(EventLogService, "event_log_service")
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
    )

    @websocket()
    async def live(  # noqa: PLR0913  # one parameter per DI'd dep; Litestar pattern
        self,
        socket: WebSocket,
        registry: SubscriberRegistry,
        handshake_timeout: float,
        docs_base_url: str,
        event_log_service: EventLogService,
        schema_change_log_service: SchemaChangeLogService,
    ) -> None:
        await socket.accept()
        try:
            hello = await _read_hello(socket, handshake_timeout)
            _validate_hello(hello, socket.auth.tenant_id)
        except SyncProtocolError as exc:
            await _close_with_problem(socket, exc, docs_base_url)
            return
        except WebSocketDisconnect:
            return

        server_seq = await event_log_service.current_seq()
        schema_version = await schema_change_log_service.current_version()
        await socket.send_json(
            Welcome(server_seq=server_seq, schema_version=schema_version)
        )

        tenant_id = socket.auth.tenant_id
        await registry.subscribe(tenant_id, socket)
        try:
            await _idle_loop(socket)
        finally:
            await registry.unsubscribe(tenant_id, socket)
