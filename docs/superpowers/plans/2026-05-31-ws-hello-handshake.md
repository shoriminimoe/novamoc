# M3.1 WebSocket Hello-Handshake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `/sync/live` WebSocket endpoint that accepts a cookie-authenticated upgrade, performs a `hello`/`welcome` handshake, and registers the connection against a (no-op for now) subscriber registry.

**Architecture:** A new `domain/sync/` package holds transport-layer infrastructure (wire payloads, protocol errors, the registry seam, the controller). The WebSocket upgrade rides the existing `SessionMiddleware → AuthenticationMiddleware → TenantContextMiddleware` stack (all engage on `ScopeType.WEBSOCKET`), so the authenticated tenant is on `socket.auth.tenant_id` and the hello's `tenant_id` is a consistency check. Protocol errors send a WS-flavoured `application/problem+json` text frame and then close with an RFC 6455 code.

**Tech Stack:** Python 3.14, Litestar (`@websocket` route handler, `WebSocket` connection), msgspec (wire structs), advanced-alchemy (DI services for the two `MAX` reads), pytest + `AsyncTestClient.websocket_connect` (real ASGI, no mocks).

**Spec:** `docs/superpowers/specs/2026-05-31-ws-hello-handshake-design.md`

---

## Orientation (read before starting)

Key facts verified during planning — trust these, they save you a round-trip:

- `litestar.WebSocket` inherits `.auth` / `.user` from `ASGIConnection`; the middleware stack populates them on WS scope. `socket.auth.tenant_id` is a `uuid.UUID`.
- `litestar.status_codes` exports `WS_1008_POLICY_VIOLATION` and `WS_1003_UNSUPPORTED_DATA`.
- `WebSocket.close(code: int = 1000, reason: str | None = None)` — reason rides in the close frame (≤123 bytes).
- `WebSocket.send_json(data)` serializes msgspec Structs via Litestar's `default_serializer`, so `send_json(Welcome(...))` emits `{"type":"welcome",...}`.
- In tests, after the server closes, the next `ws.receive_*()` raises `litestar.exceptions.WebSocketDisconnect` carrying `.code` and `.detail` (the close reason).
- `AsyncTestClient.websocket_connect(url)` returns a **sync** `WebSocketTestSession` used with a plain `with` (its `send_json` / `receive_json` are sync).
- advanced-alchemy DI services (`providers.create_service_dependencies`) resolve and read correctly inside a `@websocket` handler — verified against a throwaway app.
- The `client` conftest fixture is an authenticated `AsyncTestClient` (session cookie persisted via httpx); `unauth_client` has no session. The authenticated tenant is `tests._constants.DEV_TENANT_ID`. `DEV_TENANT_ID_B` is a distinct tenant for mismatch tests.

Run commands from the repo root. Test command shape: `uv run pytest <path> -v`. Full gate: `just check`.

---

## File structure

**Create:**
- `src/py/novamoc/domain/sync/__init__.py` — re-exports `SyncController`, `SubscriberRegistry`, `NoopSubscriberRegistry`
- `src/py/novamoc/domain/sync/_payloads.py` — `Hello`, `Welcome`, `Pong` msgspec Structs
- `src/py/novamoc/domain/sync/_registry.py` — `SubscriberRegistry` Protocol + `NoopSubscriberRegistry`
- `src/py/novamoc/domain/sync/_errors.py` — `SyncProtocolError` + subclasses
- `src/py/novamoc/domain/sync/controllers/__init__.py` — re-exports `SyncController`
- `src/py/novamoc/domain/sync/controllers/_ws.py` — `SyncController`
- `docs/problems/tenant_mismatch.md` — problem doc
- `docs/problems/handshake_timeout.md` — problem doc
- `tests/sync/__init__.py`
- `tests/sync/test_ws_handshake.py` — the e2e suite

**Modify:**
- `src/py/novamoc/config.py` — add `ws_handshake_timeout_seconds` to `AppSettings`
- `src/py/novamoc/domain/_errors.py` — add `TENANT_MISMATCH`, `HANDSHAKE_TIMEOUT` to `ErrorCode` + `_DEFAULT_MESSAGES`
- `src/py/novamoc/api/_problem_details.py` — add `_TITLES` entries + `make_ws_problem_body`
- `src/py/novamoc/asgi.py` — build `NoopSubscriberRegistry`, put on `State`, mount `SyncController`

---

## Task 1: Add the handshake-timeout setting

**Files:**
- Modify: `src/py/novamoc/config.py` (`AppSettings`, ~line 124-150)
- Test: `tests/test_config.py` (create if absent; otherwise append)

- [ ] **Step 1: Write the failing test**

Create or append to `tests/test_config.py`:

```python
from __future__ import annotations

import pytest

from novamoc.config import AppSettings


def test_ws_handshake_timeout_default() -> None:
    assert AppSettings().ws_handshake_timeout_seconds == 10.0


def test_ws_handshake_timeout_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVAMOC_WS_HANDSHAKE_TIMEOUT_SECONDS", "2.5")
    assert AppSettings().ws_handshake_timeout_seconds == 2.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'ws_handshake_timeout_seconds'`.

- [ ] **Step 3: Add the field**

In `src/py/novamoc/config.py`, inside `AppSettings`, after `schema_changes_max_batch_size`, add:

```python
    ws_handshake_timeout_seconds: float = field(
        default_factory=_float_env("NOVAMOC_WS_HANDSHAKE_TIMEOUT_SECONDS", 10.0)
    )
```

And extend the `AppSettings` docstring `Attributes:` block with:

```
        ws_handshake_timeout_seconds: How long the /sync/live WebSocket
            waits for the client's first (hello) frame before closing
            the connection. Resource-leak guard against an opened
            socket that never speaks.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): add ws_handshake_timeout_seconds setting (#36)"
```

---

## Task 2: Add the two WebSocket error codes + their problem docs

**Files:**
- Modify: `src/py/novamoc/domain/_errors.py` (`ErrorCode`, `_DEFAULT_MESSAGES`)
- Modify: `src/py/novamoc/api/_problem_details.py` (`_TITLES`)
- Create: `docs/problems/tenant_mismatch.md`, `docs/problems/handshake_timeout.md`
- Test: `tests/sync/test_problem_codes.py`

The render script (`scripts/render_problem_docs.py`, also invoked by the autouse session fixture) fails CI if a code lacks a `_TITLES` entry or a `docs/problems/<code>.md` file, so all four edits land together.

- [ ] **Step 1: Write the failing test**

Create `tests/sync/__init__.py` (empty file) and `tests/sync/test_problem_codes.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sync/test_problem_codes.py -v`
Expected: FAIL — `AttributeError: TENANT_MISMATCH`.

- [ ] **Step 3: Add the codes, messages, titles, and docs**

In `src/py/novamoc/domain/_errors.py`, add to `ErrorCode` (after `USER_ALREADY_HAS_TENANT`):

```python
    TENANT_MISMATCH = "tenant_mismatch"
    HANDSHAKE_TIMEOUT = "handshake_timeout"
```

And to `_DEFAULT_MESSAGES`:

```python
    ErrorCode.TENANT_MISMATCH: (
        "The hello frame's tenant_id does not match the authenticated tenant."
    ),
    ErrorCode.HANDSHAKE_TIMEOUT: (
        "No hello frame was received within the handshake window."
    ),
```

In `src/py/novamoc/api/_problem_details.py`, add to `_TITLES`:

```python
    ErrorCode.TENANT_MISMATCH: "Tenant mismatch",
    ErrorCode.HANDSHAKE_TIMEOUT: "Handshake timeout",
```

Create `docs/problems/tenant_mismatch.md`:

```markdown
# Tenant mismatch

The `tenant_id` carried in the WebSocket `hello` frame did not match the
tenant the connection is authenticated as. The active tenant is derived
from the session cookie on the WebSocket upgrade (ADR-017, ADR-020); the
`hello.tenant_id` is only a consistency check.

A client must send the same tenant it is logged in as. The connection is
closed with WebSocket code `1008` (policy violation).
```

Create `docs/problems/handshake_timeout.md`:

```markdown
# Handshake timeout

The client opened the `/sync/live` WebSocket but did not send its `hello`
frame within the handshake window. The server closes idle un-handshaked
sockets to avoid leaking connections.

Send the `hello` frame immediately after the socket opens. The connection
is closed with WebSocket code `1008` (policy violation).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_problem_codes.py -v`
Expected: PASS. The autouse `_render_problem_html` fixture also re-renders HTML for the two new codes without error (proving the docs exist).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/_errors.py src/py/novamoc/api/_problem_details.py docs/problems/tenant_mismatch.md docs/problems/handshake_timeout.md tests/sync/__init__.py tests/sync/test_problem_codes.py
git commit -m "feat(errors): add tenant_mismatch + handshake_timeout WS codes (#36)"
```

---

## Task 3: Wire payloads — `Hello`, `Welcome`, `Pong`

**Files:**
- Create: `src/py/novamoc/domain/sync/__init__.py` (temporary minimal; expanded in Task 6)
- Create: `src/py/novamoc/domain/sync/_payloads.py`
- Test: `tests/sync/test_payloads.py`

- [ ] **Step 1: Write the failing test**

Create `tests/sync/test_payloads.py`:

```python
from __future__ import annotations

import uuid

import msgspec

from novamoc.domain.sync._payloads import Hello, Pong, Welcome


def test_hello_decodes_with_type_tag() -> None:
    tid = uuid.uuid4()
    raw = msgspec.json.encode(
        {"type": "hello", "tenant_id": str(tid), "cursor": 7}
    )
    hello = msgspec.json.decode(raw, type=Hello)
    assert hello.tenant_id == tid
    assert hello.cursor == 7


def test_hello_rejects_unknown_field() -> None:
    raw = msgspec.json.encode(
        {"type": "hello", "tenant_id": str(uuid.uuid4()), "cursor": 0, "x": 1}
    )
    try:
        msgspec.json.decode(raw, type=Hello)
    except msgspec.ValidationError:
        return
    raise AssertionError("expected ValidationError on unknown field")


def test_hello_rejects_wrong_tag() -> None:
    raw = msgspec.json.encode(
        {"type": "welcome", "tenant_id": str(uuid.uuid4()), "cursor": 0}
    )
    try:
        msgspec.json.decode(raw, type=Hello)
    except msgspec.ValidationError:
        return
    raise AssertionError("expected ValidationError on wrong tag")


def test_welcome_encodes_with_type_tag() -> None:
    assert msgspec.json.decode(msgspec.json.encode(Welcome(server_seq=3, schema_version=4))) == {
        "type": "welcome",
        "server_seq": 3,
        "schema_version": 4,
    }


def test_pong_encodes_bare_tag() -> None:
    assert msgspec.json.decode(msgspec.json.encode(Pong())) == {"type": "pong"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sync/test_payloads.py -v`
Expected: FAIL — `ModuleNotFoundError: novamoc.domain.sync._payloads`.

- [ ] **Step 3: Create the package and payloads**

Create `src/py/novamoc/domain/sync/__init__.py`:

```python
"""Real-time sync WebSocket transport (ADR-013)."""

from __future__ import annotations
```

Create `src/py/novamoc/domain/sync/_payloads.py`:

```python
"""Wire frames for the /sync/live WebSocket (ADR-013).

JSON text frames tagged on ``type`` so the taxonomy can grow
(``event`` / ``ack`` / ``schema_changed``) in later milestones. M3.1
ships the three frames the handshake needs: the client's ``hello``, the
server's ``welcome``, and the ``pong`` reply to a client ``ping``.
"""

from __future__ import annotations

import uuid

import msgspec


class Hello(
    msgspec.Struct, forbid_unknown_fields=True, tag_field="type", tag="hello"
):
    """First client frame. ``tenant_id`` is checked against the
    cookie-authenticated tenant; ``cursor`` is the last ``event_log.seq``
    the client has applied (validated ``>= 0`` by the handler)."""

    tenant_id: uuid.UUID
    cursor: int


class Welcome(msgspec.Struct, tag_field="type", tag="welcome"):
    """Server's acceptance frame carrying the tenant's current state."""

    server_seq: int
    schema_version: int


class Pong(msgspec.Struct, tag_field="type", tag="pong"):
    """Reply to a client ``ping``."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_payloads.py -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/sync/__init__.py src/py/novamoc/domain/sync/_payloads.py tests/sync/test_payloads.py
git commit -m "feat(sync): hello/welcome/pong WS wire frames (#36)"
```

---

## Task 4: Protocol errors + `make_ws_problem_body`

**Files:**
- Create: `src/py/novamoc/domain/sync/_errors.py`
- Modify: `src/py/novamoc/api/_problem_details.py` (add `make_ws_problem_body`)
- Test: `tests/sync/test_errors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/sync/test_errors.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sync/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: novamoc.domain.sync._errors`.

- [ ] **Step 3: Implement the errors and the body builder**

Create `src/py/novamoc/domain/sync/_errors.py`:

```python
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

from novamoc.domain._errors import ErrorCode, _DEFAULT_MESSAGES


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
```

In `src/py/novamoc/api/_problem_details.py`, add after `make_problem_body` (keep `make_instance`, `_type_uri`, `_TITLES` usage consistent):

```python
def make_ws_problem_body(
    *,
    code: ErrorCode,
    close_code: int,
    detail: str,
    base_url: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """RFC 9457 problem body for a WebSocket protocol error.

    Sent as a final text frame before the socket closes, so a client can
    branch on the same ``type`` URI it would see on the HTTP error. There
    is no HTTP ``status`` slot (a WS error has no HTTP status); the close
    code rides as the ``ws_close_code`` extension member (RFC 9457 §3.2).
    """
    body: dict[str, Any] = {
        "type": _type_uri(code, base_url),
        "title": _TITLES[code],
        "detail": detail,
        "instance": make_instance(),
        "ws_close_code": close_code,
    }
    if extras:
        body.update(extras)
    return body
```

Note: `Any` is already imported in `_problem_details.py`. `ErrorCode` is already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_errors.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/sync/_errors.py src/py/novamoc/api/_problem_details.py tests/sync/test_errors.py
git commit -m "feat(sync): protocol errors + make_ws_problem_body (#36)"
```

---

## Task 5: Subscriber registry seam

**Files:**
- Create: `src/py/novamoc/domain/sync/_registry.py`
- Test: `tests/sync/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/sync/test_registry.py`:

```python
from __future__ import annotations

import uuid

from novamoc.domain.sync._registry import (
    NoopSubscriberRegistry,
    SubscriberRegistry,
)


async def test_noop_registry_methods_are_callable() -> None:
    reg = NoopSubscriberRegistry()
    tid = uuid.uuid4()
    # No socket object needed — the no-op ignores it.
    await reg.subscribe(tid, object())  # type: ignore[arg-type]
    await reg.unsubscribe(tid, object())  # type: ignore[arg-type]
    await reg.publish(tid, b"payload")


def test_noop_satisfies_protocol() -> None:
    reg: SubscriberRegistry = NoopSubscriberRegistry()
    assert isinstance(reg, SubscriberRegistry)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sync/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: novamoc.domain.sync._registry`.

- [ ] **Step 3: Implement the registry**

Create `src/py/novamoc/domain/sync/_registry.py`:

```python
"""Subscriber registry seam (ADR-013 fan-out scoping).

M3.1 ships the interface and a no-op implementation so the handshake
path can call ``subscribe`` / ``unsubscribe`` before the real in-memory
map lands in #37. The Protocol is the narrow ``publish`` / ``subscribe``
/ ``unsubscribe`` surface #37 asks for, kept transport-mechanical (the
registry fans out opaque pre-encoded ``bytes``) so a future deployment
can swap a Redis-backed store without touching the controller.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from litestar import WebSocket


@runtime_checkable
class SubscriberRegistry(Protocol):
    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...

    async def unsubscribe(
        self, tenant_id: uuid.UUID, socket: WebSocket
    ) -> None: ...

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None: ...


class NoopSubscriberRegistry:
    """Placeholder until the real registry lands (#37). All methods are
    no-ops so the handshake path is exercisable now."""

    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
        return

    async def unsubscribe(
        self, tenant_id: uuid.UUID, socket: WebSocket
    ) -> None:
        return

    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_registry.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/sync/_registry.py tests/sync/test_registry.py
git commit -m "feat(sync): SubscriberRegistry protocol + no-op impl (#36)"
```

---

## Task 6: The controller + mounting + happy-path e2e

This is the integration task: the controller, its package exports, the `asgi` wiring, and the first end-to-end test (which is also the controller's primary test).

**Files:**
- Create: `src/py/novamoc/domain/sync/controllers/__init__.py`
- Create: `src/py/novamoc/domain/sync/controllers/_ws.py`
- Modify: `src/py/novamoc/domain/sync/__init__.py` (expand exports)
- Modify: `src/py/novamoc/asgi.py` (registry on State + mount controller)
- Test: `tests/sync/test_ws_handshake.py`

- [ ] **Step 1: Write the failing happy-path test**

Create `tests/sync/test_ws_handshake.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_hello_handshake_returns_welcome(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        welcome = ws.receive_json()
    assert welcome == {"type": "welcome", "server_seq": 0, "schema_version": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sync/test_ws_handshake.py -v`
Expected: FAIL — the route `/sync/live` does not exist (connection rejected / 404).

- [ ] **Step 3: Implement the controller**

Create `src/py/novamoc/domain/sync/controllers/_ws.py`:

```python
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
from typing import TYPE_CHECKING

import msgspec
from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, WebSocket, websocket
from litestar.datastructures import State  # noqa: TC002  # runtime DI provider
from litestar.di import Provide
from litestar.exceptions import WebSocketDisconnect, WebSocketException
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

if TYPE_CHECKING:
    import uuid

    from novamoc.domain.sync._registry import SubscriberRegistry


async def _provide_registry(state: State) -> SubscriberRegistry:
    return state.subscriber_registry


async def _provide_handshake_timeout(state: State) -> float:
    return state.settings.app.ws_handshake_timeout_seconds


async def _provide_docs_base_url(state: State) -> str:
    return state.settings.app.docs_base_url


async def _read_hello(socket: WebSocket, timeout: float) -> Hello:
    try:
        async with asyncio.timeout(timeout):
            raw = await socket.receive_text()
    except TimeoutError as exc:
        raise HandshakeTimeoutError() from exc
    try:
        return msgspec.json.decode(raw.encode("utf-8"), type=Hello)
    except msgspec.MsgspecError as exc:
        raise MalformedHelloError(str(exc)) from exc


def _validate_hello(hello: Hello, auth_tenant_id: uuid.UUID) -> None:
    if hello.tenant_id != auth_tenant_id:
        raise TenantMismatchError()
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
    try:
        await socket.send_json(body)
    except (WebSocketException, WebSocketDisconnect, RuntimeError):
        pass
    await socket.close(code=exc.close_code, reason=exc.code.value)


async def _idle_loop(socket: WebSocket) -> None:
    while True:
        try:
            frame = await socket.receive_json()
        except WebSocketDisconnect:
            return
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
```

Create `src/py/novamoc/domain/sync/controllers/__init__.py`:

```python
from ._ws import SyncController

__all__ = ("SyncController",)
```

Expand `src/py/novamoc/domain/sync/__init__.py`:

```python
"""Real-time sync WebSocket transport (ADR-013)."""

from __future__ import annotations

from novamoc.domain.sync._registry import (
    NoopSubscriberRegistry,
    SubscriberRegistry,
)
from novamoc.domain.sync.controllers import SyncController

__all__ = ("NoopSubscriberRegistry", "SubscriberRegistry", "SyncController")
```

- [ ] **Step 4: Mount it in `asgi.create_app`**

In `src/py/novamoc/asgi.py`:

Add to the deferred-import block (near the other domain imports):

```python
    from novamoc.domain.sync import NoopSubscriberRegistry, SyncController
```

After `password_hasher = PasswordHasher(...)` (before `_assert_alembic_at_head`), add:

```python
    subscriber_registry = NoopSubscriberRegistry()
```

Add `SyncController` to `route_handlers` (after `SnapshotController`):

```python
            SnapshotController,
            SyncController,
            problem_docs_router,
```

Add the registry to `State`:

```python
        state=State(
            {
                "settings": s,
                "password_hasher": password_hasher,
                "subscriber_registry": subscriber_registry,
            }
        ),
```

Do **not** add `/sync/live` to the `AuthenticationMiddleware` `exclude` pattern — the endpoint requires auth.

- [ ] **Step 5: Run the happy-path test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py -v`
Expected: PASS — `welcome == {"type": "welcome", "server_seq": 0, "schema_version": 0}`.

- [ ] **Step 6: Add a welcome-reflects-state assertion**

Append to `tests/sync/test_ws_handshake.py`:

```python
async def test_welcome_reflects_current_schema_version(client: AsyncTestClient) -> None:
    # Create one schema entity so schema_version advances to 1.
    resp = await client.post(
        "/schema",
        json={
            "command": "create_asset_type",
            "payload": {"name": "Truck", "description": "A truck"},
        },
    )
    assert resp.status_code == 201, resp.text

    with client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        welcome = ws.receive_json()
    assert welcome["schema_version"] == 1
```

Note: verify the exact `create_asset_type` payload against `tests/schema/test_endpoint_e2e.py` before running — copy a known-good create body from there if the shape differs.

- [ ] **Step 7: Run both tests**

Run: `uv run pytest tests/sync/test_ws_handshake.py -v`
Expected: PASS (both).

- [ ] **Step 8: Commit**

```bash
git add src/py/novamoc/domain/sync/ src/py/novamoc/asgi.py tests/sync/test_ws_handshake.py
git commit -m "feat(sync): /sync/live hello handshake + welcome (#36)"
```

---

## Task 7: e2e — tenant mismatch closes 1008

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/sync/test_ws_handshake.py` (add `import pytest`, `from litestar.exceptions import WebSocketDisconnect`, and `from tests._constants import DEV_TENANT_ID_B` to the imports):

```python
async def test_tenant_mismatch_closes_1008(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json(
            {"type": "hello", "tenant_id": str(DEV_TENANT_ID_B), "cursor": 0}
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/tenant_mismatch.html")
        assert problem["ws_close_code"] == 1008
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1008
    assert exc_info.value.detail == "tenant_mismatch"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py::test_tenant_mismatch_closes_1008 -v`
Expected: PASS (the controller from Task 6 already implements this path).

If it FAILS because the problem frame and close arrive coalesced, adjust: read the close via `pytest.raises(WebSocketDisconnect)` around the *first* `receive_json` and assert `exc_info.value.code`/`.detail` only — but the two-step (frame then disconnect) is the expected behavior given `send_json` precedes `close`.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): tenant mismatch closes 1008 with problem frame (#36)"
```

---

## Task 8: e2e — malformed hello (1003) and negative cursor (1008)

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

- [ ] **Step 1: Write the failing tests**

Append:

```python
async def test_unknown_field_closes_1003(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json(
            {
                "type": "hello",
                "tenant_id": str(DEV_TENANT_ID),
                "cursor": 0,
                "bogus": 1,
            }
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/invalid_payload_shape.html")
        assert problem["ws_close_code"] == 1003
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1003


async def test_wrong_tag_closes_1003(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json(
            {"type": "welcome", "tenant_id": str(DEV_TENANT_ID), "cursor": 0}
        )
        problem = ws.receive_json()
        assert problem["ws_close_code"] == 1003
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


async def test_negative_cursor_closes_1008(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json(
            {"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": -1}
        )
        problem = ws.receive_json()
        assert problem["type"].endswith("/problems/invalid_payload_shape.html")
        assert problem["ws_close_code"] == 1008
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
    assert exc_info.value.code == 1008
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sync/test_ws_handshake.py -k "1003 or negative_cursor" -v`
Expected: PASS (all three — controller already implements these paths).

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): malformed hello (1003) + negative cursor (1008) (#36)"
```

---

## Task 9: e2e — handshake timeout

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

The default 10s timeout is too long for a test. The handler reads the
window from `state.settings.app.ws_handshake_timeout_seconds` *at request
time* (via `_provide_handshake_timeout`), so the test just swaps in a
modified `Settings` copy on the existing client's app — no app rebuild
needed. The `app` / `client` fixtures are function-scoped, so the
mutation does not leak to other tests.

- [ ] **Step 1: Write the failing test**

Add `from dataclasses import replace` to the imports, then append:

```python
async def test_handshake_timeout_closes_1008(client, app, settings) -> None:
    # The handler reads the window from state.settings at request time,
    # so a modified copy on app.state shortens the handshake budget.
    app.state.settings = replace(
        settings, app=replace(settings.app, ws_handshake_timeout_seconds=0.2)
    )
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/sync/live") as ws:
            # Send nothing; wait past the window for the server to close.
            ws.receive_json()
    assert exc_info.value.code == 1008
    assert exc_info.value.detail == "handshake_timeout"
```

Note: `Settings` and `AppSettings` are frozen dataclasses, so
`dataclasses.replace` is the correct way to produce a modified copy.

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py::test_handshake_timeout_closes_1008 -v`
Expected: PASS — the socket closes ~0.2s after open with code 1008, reason `handshake_timeout`.

If the test hangs: confirm `asyncio.timeout` wraps `receive_text` in `_read_hello` and that `TimeoutError` (the builtin; `asyncio.TimeoutError` is an alias for it in 3.14) is caught.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): handshake timeout closes 1008 (#36)"
```

---

## Task 10: e2e — unauthenticated upgrade is rejected

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

This pins that the WS scope flows through `AuthenticationMiddleware` (the rejection itself is already covered by the accounts suite). Uses the `unauth_client` fixture (no session cookie).

- [ ] **Step 1: Write the failing test**

Append:

```python
async def test_unauthenticated_upgrade_rejected(unauth_client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with unauth_client.websocket_connect("/sync/live") as ws:
            ws.send_json(
                {"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0}
            )
            ws.receive_json()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py::test_unauthenticated_upgrade_rejected -v`
Expected: PASS — the middleware raises `NotAuthorizedException` during the upgrade, so the connection never reaches the handler; the client sees a `WebSocketDisconnect`.

If the connect raises on `__enter__` rather than on `receive_json`, the `pytest.raises` wrapping both lines still catches it. If it does NOT raise at all (handler reached without auth): that's a real bug — investigate the middleware `exclude` pattern (it must not match `/sync/live`).

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): unauthenticated WS upgrade is rejected (#36)"
```

---

## Task 11: e2e — ping/pong

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
async def test_ping_gets_pong(client: AsyncTestClient) -> None:
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py::test_ping_gets_pong -v`
Expected: PASS (the idle loop answers ping with pong).

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): ping gets pong in the idle loop (#36)"
```

---

## Task 12: e2e — registry subscribe/unsubscribe seam

**Files:**
- Test: `tests/sync/test_ws_handshake.py` (append)

Override `app.state.subscriber_registry` with a spy (the `_provide_registry` provider reads it at request time), connect, complete the handshake, disconnect, and assert one `subscribe` and one `unsubscribe`.

- [ ] **Step 1: Write the failing test**

Append:

```python
class _SpyRegistry:
    def __init__(self) -> None:
        self.subscribed: list = []
        self.unsubscribed: list = []

    async def subscribe(self, tenant_id, socket) -> None:
        self.subscribed.append(tenant_id)

    async def unsubscribe(self, tenant_id, socket) -> None:
        self.unsubscribed.append(tenant_id)

    async def publish(self, tenant_id, message) -> None:
        return


async def test_registry_subscribe_unsubscribe_called(
    client: AsyncTestClient, app
) -> None:
    spy = _SpyRegistry()
    app.state.subscriber_registry = spy
    with client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"
    # Exiting the context closes the socket; the handler's finally runs
    # unsubscribe before the task completes.
    assert spy.subscribed == [DEV_TENANT_ID]
    assert spy.unsubscribed == [DEV_TENANT_ID]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/sync/test_ws_handshake.py::test_registry_subscribe_unsubscribe_called -v`
Expected: PASS.

If `unsubscribed` is empty: the test client may not join the server task on close. Add an explicit `ws.close()` before exiting the `with`, and if still racy, assert `subscribed` synchronously and move the `unsubscribed` assertion after a `await asyncio.sleep(0)` to yield to the handler's finally. Prefer the no-sleep version first.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_ws_handshake.py
git commit -m "test(sync): registry subscribe/unsubscribe seam (#36)"
```

---

## Task 13: Full gate + ratchet

**Files:**
- Possibly modify: `.ruff-ratchet.json` (only if counts legitimately decreased)

- [ ] **Step 1: Run the full check**

Run: `just check`
Expected: lint + format + typecheck + test all green. `just check` includes `db-check` and the ratchet.

- [ ] **Step 2: Resolve lint findings the right way**

If ruff flags new violations, follow the repo ratchet workflow (CLAUDE.md): read `uv run ruff rule <code>`, try `uv run ruff check --fix` (safe fixes only), fix manually otherwise. The `noqa: PLR0913` on `live(...)` and `noqa: TC002` on the `State` import are pre-justified (Litestar DI patterns, mirroring `EventsController`). Do not add new project-wide ignores without flagging.

- [ ] **Step 3: Update the ratchet only if counts dropped**

If `just ratchet` reports counts *decreased*, run `just ratchet-update` and stage `.ruff-ratchet.json`. If counts would *increase*, fix the violations instead — do not bump the baseline.

- [ ] **Step 4: Run the whole sync suite once more**

Run: `uv run pytest tests/sync/ -v`
Expected: every test green.

- [ ] **Step 5: Commit any ratchet/lint follow-ups**

```bash
git add -A
git commit -m "chore(sync): satisfy lint + ratchet for M3.1 (#36)"
```

(Skip this commit if there was nothing to change.)

---

## Self-review notes (planner)

- **Spec coverage:** path/auth-posture/hello-name departures → Task 6 + spec doc; `Hello`/`Welcome` shape → Task 3; `server_seq`/`schema_version` in welcome → Task 6 (services); tenant-match + cursor-sign + frame-shape + timeout validation table → Tasks 6-9; no schema-version gate (deferred) → not implemented, by design; registry Protocol/no-op + `publish` included → Task 5; `make_ws_problem_body` sibling (not extending `make_problem_body`) → Task 4; new error codes + doc ripple → Task 2; handshake timeout setting → Task 1; idle loop ignore-and-continue + ping/pong → Tasks 6, 11; all eight test scenarios → Tasks 6-12; problem-docs coverage via `render_all` → Task 2. No gaps.
- **No `tenant_id` passed to reads:** the two `MAX` services rely on Layer-1 scoping; correct per CLAUDE.md.
- **Type consistency:** `SyncProtocolError(code=, close_code=, message=, extras=)` constructor is used identically in `_errors.py`, `_validate_hello`, and `make_ws_problem_body`. `current_seq()` (events) and `current_version()` (schema) are the verified method names. `socket.auth.tenant_id` is `uuid.UUID`, matching `Hello.tenant_id`.
- **Out of scope (later issues):** registry implementation (#37), fan-out (#38), resume (#39), heartbeat timeout, client→server event push, ADR-013 acceptance (#40).
```
