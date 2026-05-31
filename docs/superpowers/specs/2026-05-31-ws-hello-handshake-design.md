# M3.1 — WebSocket endpoint with hello handshake

**Issue:** #36 (M3 — WebSocket transport and fan-out)
**Refs:** ADR-013 (HTTP and WebSocket transports), ADR-017 / ADR-020 (tenant
resolution + authentication), ADR-011 (append-only event log), ADR-016 (RFC 9457
problem details).
**Status:** Approved, ready for implementation planning.

## Summary

Add the real-time sync WebSocket endpoint at `/sync/live`. A client opens the
socket, sends a single `hello` frame, and the server validates it and registers
the subscription, replying with a `welcome` frame carrying the tenant's current
`server_seq` and `schema_version`. This is the handshake half of ADR-013's
WebSocket transport; the subscriber registry (#37), fan-out hook (#38), and
resume-before-live-delivery (#39) build on top of the seam this issue
establishes.

## Departures from the issue text (and why)

The issue (#36) was written before authentication landed (ADR-020), so two of
its statements are superseded:

1. **Path.** The issue says `/ws`; the chosen path is `/sync/live` — descriptive
   of the resource rather than the transport (the `wss://` scheme already says
   "websocket"), and exactly what ADR-013 already specifies, so the M3.5 ADR
   acceptance pass (#40) needs no ADR amendment.
2. **Auth posture.** The issue says "until auth lands the tenant id is taken from
   the hello message." Auth *has* landed. The WebSocket upgrade flows through the
   same middleware stack as HTTP — `SessionMiddleware → AuthenticationMiddleware →
   TenantContextMiddleware`, all three of which engage on `ScopeType.WEBSOCKET`.
   So the cookie-derived tenant on `scope["auth"].tenant_id` is authoritative;
   the hello frame's `tenant_id` is a **consistency check** against it, not the
   source of identity. A mismatch closes the socket. This keeps the WebSocket on
   the same authentication footing ADR-017 pinned for every other request.
3. **Hello field name.** The issue says `last_seen_seq`; the spec uses `cursor` to
   match `GET /events`'s `CursorPagination` cursor — the same concept under the
   same name across the data-sync protocol.

## Architecture

New package `src/py/novamoc/domain/sync/` — transport-layer infrastructure for
real-time sync, kept distinct from `domain/events/` (which owns event semantics,
validation, and the HTTP `/events` endpoints). Sync is where the broadcaster
(#38) and resume logic (#39) will also live, and where a future `schema_changed`
fan-out belongs — none of which is *event-semantic*, all of which is *transport*.

```
src/py/novamoc/domain/sync/
├── __init__.py           # re-exports SyncController, SubscriberRegistry,
│                         #   NoopSubscriberRegistry
├── _payloads.py          # Hello, Welcome msgspec Structs
├── _registry.py          # SubscriberRegistry Protocol + NoopSubscriberRegistry
├── _errors.py            # SyncProtocolError hierarchy (WS close code + ErrorCode)
└── controllers/
    ├── __init__.py
    └── _ws.py            # SyncController exposing @websocket("/sync/live")
```

### Mounting and DI

- `SyncController(path="/sync/live")` is added to `route_handlers` in
  `asgi.create_app`, alongside the existing controllers.
- `create_app` constructs one `NoopSubscriberRegistry()` and stashes it on
  `State`:
  `state={"settings": s, "password_hasher": ..., "subscriber_registry": registry}`.
  A controller-level DI provider `_provide_registry(state) -> SubscriberRegistry`
  hands it to the handler. **M3.2 (#37) changes only the line in `create_app`
  that builds the singleton** — the controller is untouched.
- No middleware changes. The upgrade already flows through the full middleware
  stack because all three middlewares engage on `ScopeType.WEBSOCKET`
  (`AbstractAuthenticationMiddleware.scopes` defaults to `{HTTP, WEBSOCKET}`;
  `ASGIMiddleware.scopes` covers HTTP/WS/ASGI). Inside the handler,
  `socket.auth.tenant_id` is the authenticated tenant and `current_tenant_id` is
  already bound for any DB reads.

## Wire protocol

JSON text frames, encoded/decoded with msgspec (matching the HTTP endpoints).
Frames are tagged with `type` so the message taxonomy can grow (`event`, `ack`,
`schema_changed`, `pong`) in later milestones.

```python
class Hello(Struct, forbid_unknown_fields=True, tag_field="type", tag="hello"):
    tenant_id: uuid.UUID
    cursor: int          # last seq the client has applied; validated >= 0

class Welcome(Struct, tag_field="type", tag="welcome"):
    server_seq: int      # current MAX(event_log.seq) for the tenant; 0 if none
    schema_version: int  # current MAX(schema_change_log.seq) for the tenant; 0 if none
```

`server_seq` and `schema_version` are computed (one cheap `MAX` query each, via
the existing `EventLogService` and `SchemaChangeLogService.current_version()`)
and included even though M3.1 doesn't yet act on them — it lets M3.4's resume and
any future schema-gating read a complete welcome from day one rather than
reshaping the frame later. Layer-1 tenant scoping (`db._listeners`) supplies the
`WHERE tenant_id` predicate on both aggregates automatically.

## Handshake sequence (inside `SyncController.live`)

1. `await socket.accept()` — complete the upgrade. (Authentication already
   happened in middleware; an unauthenticated upgrade is rejected there and never
   reaches the handler.)
2. Read exactly one frame, bounded by the handshake timeout (below). Decode as
   `Hello`. Decode failure / wrong tag / unknown field → `MalformedHelloError`.
3. Validate (below). Failure raises the matching `SyncProtocolError`.
4. Compute `server_seq` + `schema_version`; send `Welcome`.
5. `await registry.subscribe(tenant_id, socket)`.
6. Enter the idle loop (below). A `try/finally` around steps 5–6 guarantees
   `await registry.unsubscribe(tenant_id, socket)` on any exit.

Protocol errors raised in steps 2–4 are caught by a single handler-level
`except SyncProtocolError` that runs the close helper (below) and returns.

## Validation rules

| Check | Rule | On failure |
|---|---|---|
| Tenant match | `hello.tenant_id == socket.auth.tenant_id` | `TenantMismatchError` → close `1008`, code `tenant_mismatch` |
| Cursor sign | `hello.cursor >= 0` | close `1008`, code `invalid_payload_shape` |
| Frame shape | decodes as a `hello`-tagged `Hello` (`forbid_unknown_fields=True`) | `MalformedHelloError` → close `1003`, code `invalid_payload_shape` |
| First-frame timeout | hello arrives within the handshake window | `HandshakeTimeoutError` → close `1008`, code `handshake_timeout` |

Notes:

- **No `schema_version` gate in the hello for M3.1.** ADR-013's stale-client
  rejection is about *event flow*, which doesn't begin until M3.3. M3.1 reports
  the current `schema_version` in the welcome and lets the client decide; adding
  a reject path now would be speculative. Deliberate deferral.
- **`socket.auth` is guaranteed populated.** A missing/invalid cookie makes
  `AuthenticationMiddleware` raise `NotAuthorizedException` during the upgrade;
  the handler never runs. There is no "unauthenticated" branch inside the
  handler — that path belongs to the middleware (already covered by the accounts
  suite); M3.1 adds one e2e test pinning that the WS scope really flows through
  it.
- **`cursor >= 0`** is validated by hand rather than via a msgspec `Meta(ge=0)`
  constraint, so the close-code mapping stays in one place instead of catching
  and re-mapping a `msgspec.ValidationError`.

## The registry seam (`_registry.py`)

The interface is the narrow `publish` / `subscribe` / `unsubscribe` that #37
asks for. M3.1 ships the Protocol and a no-op implementation; M3.2 writes the
real in-memory `dict[uuid.UUID, set[WebSocket]]` map against the same Protocol.

```python
class SubscriberRegistry(Protocol):
    async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...
    async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None: ...
    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None: ...

class NoopSubscriberRegistry:
    """M3.1 placeholder; all three methods are no-ops so the handshake
    path is exercisable before the real registry lands (#37)."""
```

Decisions:

- **Methods are `async`** from the start because the real `publish` will
  `await socket.send_*` per subscriber. M3.2 doesn't get to change the signature.
- **`publish` is on the Protocol now** even though M3.1 never calls it — it's the
  third verb #37 names, and pinning the full interface in one commit means #38
  adds a caller, not a method.
- **`message: bytes`** — pre-encoded frame payload; the registry stays
  transport-mechanical (fans out opaque bytes), encoding lives in the broadcaster.
  This is what keeps the interface swappable for a Redis pubsub later (#37).
- **Keyed by `tenant_id`** — ADR-013 fan-out scoping.

## Error handling (`_errors.py` + `make_ws_problem_body`)

A small exception hierarchy mirrors how the HTTP side carries an `ErrorCode`, but
with a WS close code instead of an HTTP status:

```python
class SyncProtocolError(Exception):
    close_code: int        # RFC 6455, e.g. WS_1008_POLICY_VIOLATION
    code: ErrorCode

class TenantMismatchError(SyncProtocolError):   # 1008 / tenant_mismatch
class HandshakeTimeoutError(SyncProtocolError): # 1008 / handshake_timeout
class MalformedHelloError(SyncProtocolError):   # 1003 / invalid_payload_shape
```

(The negative-cursor case reuses `MalformedHelloError`'s code
`invalid_payload_shape` but with close code `1008`; it raises a
`SyncProtocolError` constructed with that code/close-code pair rather than its
own subclass, since it's a value error not a shape error.)

**Close helper** — a single function does the two-step "structured reason then
close":

1. `await socket.send_text(problem_json)` — a final text frame whose body is
   `make_ws_problem_body(...)`-shaped, so a client can branch on the same `type`
   URI it sees on the HTTP error. **Best-effort**: wrapped so a send failure on an
   already-half-closed socket does not mask the original error.
2. `await socket.close(code=err.close_code, reason=err.code.value)`. The bare
   code string is well under RFC 6455's 123-byte reason budget.

**`make_ws_problem_body`** is a ~10-line sibling of `make_problem_body` in
`api/_problem_details.py` (chosen over extending `make_problem_body`, which reads
an HTTP `status_code` a WS error doesn't have — faking that field to reuse the
function is coupling we'd regret). It reads `_TITLES` for one source of truth and
emits:

```json
{ "type": "<base>/problems/<code>.html", "title": "...", "detail": "...",
  "instance": "urn:uuid:...", "ws_close_code": 1008 }
```

No HTTP `status` slot (there is no HTTP status on a WS error); `ws_close_code` is
the RFC 9457 §3.2 extension member.

### New error codes and their problem-doc ripple

Two new `ErrorCode` members are added: `TENANT_MISMATCH` and `HANDSHAKE_TIMEOUT`
(malformed hello and negative cursor reuse the existing `INVALID_PAYLOAD_SHAPE`).
The problem-details system enforces, in lockstep (the render script fails CI
otherwise), for each new code:

- entry in `ErrorCode` enum + `_DEFAULT_MESSAGES` (`domain/_errors.py`)
- entry in `_TITLES` (`api/_problem_details.py`)
- an authored `docs/problems/<code>.md`

`PROBLEM_CODES` (`api/_problem_codes.py`) picks them up automatically — it's
derived from `ErrorCode`.

## Handshake timeout

The first-frame read is wrapped in `asyncio.timeout(...)`. A client that opens
the socket and never sends a hello is closed rather than parked forever (a cheap
resource-leak guard). The window is a new setting
`settings.app.ws_handshake_timeout_seconds`, default **10.0** — production-safe by
default; dev does not override it. On expiry → `HandshakeTimeoutError` → close
`1008`.

## Idle loop (the M3.1 boundary)

After `Welcome` + `subscribe`, the handler enters a receive loop that does the
minimum to keep a healthy connection alive and to be a clean insertion point for
later milestones:

- `ping` frame → reply `pong`. (ADR-013 heartbeat; the dead-connection *timeout*
  side is a later M3 issue — M3.1 only answers pings.)
- Any other frame → **ignore and continue** (do not close). Client→server `event`
  push and `schema_changed` are valid protocol frames that later milestones
  handle; closing on them now would be wrong.
- `WebSocketDisconnect` → break the loop; the enclosing `try/finally` runs
  `unsubscribe`.

The loop body is a deliberate stub. M3.3 replaces "ignore other frames" with
broadcaster wiring; M3.4 inserts the resume-before-live step ahead of the loop.

## Testing

Real ASGI WebSocket tests via `AsyncTestClient` (no mocks — repo rule). New
`tests/sync/` package, reusing the existing `app` / `client` / `tenant` conftest
machinery.

- **Happy path** — authenticated client connects, sends valid `hello`, receives
  `welcome` with correct `server_seq` / `schema_version` (seed an event + a schema
  change, assert the MAX values).
- **Tenant mismatch** — `hello.tenant_id` ≠ authenticated tenant → close `1008`,
  final frame carries the `tenant_mismatch` problem body.
- **Malformed hello** — bad JSON / unknown field / wrong tag → close `1003`,
  `invalid_payload_shape`.
- **Negative cursor** — `cursor < 0` → close `1008`, `invalid_payload_shape`.
- **Handshake timeout** — connect, send nothing → close `1008` `handshake_timeout`
  within the window (test overrides the setting to a small value).
- **Unauthenticated upgrade** — no session cookie → upgrade rejected by
  middleware (pins that the WS scope flows through auth).
- **Ping/pong** — after welcome, `ping` → `pong`.
- **Registry seam** — a spy/fake `SubscriberRegistry` injected via DI override
  asserts `subscribe` / `unsubscribe` are each called once across
  connect/disconnect.
- **Problem-docs coverage** — `render_all()` already runs in the suite; it fails
  if a new code lacks a doc, so no extra test is needed.

## Out of scope (later M3 issues)

- Subscriber registry implementation — #37 (M3.2).
- Fan-out on event acceptance — #38 (M3.3).
- Resume from cursor before live delivery — #39 (M3.4).
- Dead-connection heartbeat *timeout* (server-side ping deadline) — later M3.
- Client→server event push over WS and `ack` frames — deferred (v1 event push is
  HTTP `POST /events`).
- Flipping ADR-013 to Accepted — #40 (M3.5).
