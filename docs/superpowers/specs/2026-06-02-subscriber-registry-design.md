# M3.2 — In-memory subscriber registry

**Issue:** #37 (M3 — WebSocket transport and fan-out)
**Refs:** ADR-013 (HTTP and WebSocket transports; the single-process subscriber registry), ADR-014/ADR-017 (tenant scoping).
**Status:** Approved, ready for implementation planning.

## Summary

Replace the `NoopSubscriberRegistry` placeholder (landed with #36) with a working
`InMemorySubscriberRegistry`: an in-process `dict[tenant_id, set[WebSocket]]` that
fans a pre-encoded message out to a tenant's connected sockets. The
`SubscriberRegistry` Protocol already exists; this issue fills it in. The
fan-out *caller* (publishing accepted events) is the next issue (#38); here
`publish` is built and unit-tested in isolation.

## Scope boundary: registry vs. durable queue

The subscriber registry is a *per-process* map of live socket handles — it holds
which connections on this process are subscribed to a tenant, so something can
call `.send()` on them. It is inherently in-memory and ephemeral (a socket handle
cannot be serialized to an external store). A durable queue / cross-process
pub-sub solves a *different* problem (how multiple processes learn about an
accepted event) and would sit *in front of* the registry, not replace it. That
is the fan-out / multi-process concern ADR-013 explicitly defers, and is out of
scope here. For v1's single-process deployment, the in-memory registry is
sufficient (ADR-013), and the existing Protocol seam lets a future deployment
swap the backing distribution mechanism without touching the controller.

## Architecture

`InMemorySubscriberRegistry` lives in `src/py/novamoc/domain/sync/_registry.py`
beside the `SubscriberRegistry` Protocol it implements. `NoopSubscriberRegistry`
is removed — its stated job ("until the real registry is implemented") is done,
and pre-release there is no back-compat to preserve.

`asgi.create_app` constructs `InMemorySubscriberRegistry()` instead of the Noop
and stores it on `State` under `subscriber_registry`. This is the only
controller-facing change; the controller resolves the registry via the existing
`_provide_registry` DI provider and calls `subscribe` / `unsubscribe` exactly as
before.

## State

```python
self._subscribers: dict[uuid.UUID, set[WebSocket]]
```

Keyed by `tenant_id` (ADR-013 fan-out scoping). The value is a `set` of live
`WebSocket` handles, deduplicated by identity (`WebSocket` is hashable; it does
not override `__eq__`, so set membership is identity-based — exactly right for
distinct connections).

## Methods

```python
async def subscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
    self._subscribers.setdefault(tenant_id, set()).add(socket)

async def unsubscribe(self, tenant_id: uuid.UUID, socket: WebSocket) -> None:
    subscribers = self._subscribers.get(tenant_id)
    if subscribers is None:
        return
    subscribers.discard(socket)
    if not subscribers:
        del self._subscribers[tenant_id]

async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
    for socket in list(self._subscribers.get(tenant_id, ())):
        with contextlib.suppress(WebSocketException, RuntimeError):
            await socket.send_data(message, mode="text")
```

Notes:

- `subscribe` / `unsubscribe` perform only synchronous `dict`/`set` mutation — no
  `await` — so they are atomic relative to `publish` on the single event loop.
- `unsubscribe` is idempotent (`discard`, and a missing tenant returns) and
  prunes the tenant entry when its set empties, so empty sets don't accumulate.
- `publish` **snapshots** the tenant's set (`list(...)`) before its first
  `await`, so a `subscribe`/`unsubscribe` landing mid-fan-out cannot mutate the
  collection being iterated. A socket subscribed *after* the snapshot misses this
  message (it will receive subsequent ones; the gap-close handshake in ADR-013
  covers the catch-up window).

## Concurrency

Single process ⇒ single asyncio event loop. Because `subscribe`/`unsubscribe`
never `await`, they cannot interleave partway through `publish`; and `publish`
copies the set before awaiting, so concurrent mutation is safe without a lock.
No `asyncio.Lock` and no `threading.Lock` — production (granian) runs WS handlers
on the loop, so there is no cross-thread access in v1.

## Send mode

`publish` receives a pre-encoded message as `bytes` (the broadcaster in #38 will
`msgspec.json.encode` events to bytes). `send_data(message, mode="text")` decodes
those bytes into a UTF-8 WebSocket *text* frame, matching the JSON-text wire
format clients consume via `receive_json`. The registry stays
transport-mechanical: it fans out opaque bytes and does not interpret them.

## Error handling

`publish` is best-effort per socket: each send is wrapped in
`contextlib.suppress(WebSocketException, RuntimeError)` so a closed/closing peer
cannot abort delivery to the rest of the tenant's subscribers. Dead sockets are
removed by their own handler's `unsubscribe` (the controller's `finally`) — the
single authoritative cleanup path; `publish` does not prune, avoiding two code
paths racing to remove the same socket. `subscribe`/`unsubscribe` cannot fail
(pure dict ops). The registry never raises into the controller.

## Testing

Unit tests against the registry directly, with a tiny fake socket that records
its `send_data` calls. The registry touches no database, so no app/engine
fixtures are needed (this is not the "no DB mocks" rule's territory — there is no
DB here). The fake:

```python
class _FakeSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[bytes] = []
        self._fail = fail

    async def send_data(self, data: bytes, mode: str = "text") -> None:
        if self._fail:
            raise WebSocketException("boom")
        self.sent.append(data)
```

Cases:

- **deliver** — subscribe one socket, `publish` → the socket's `sent` holds the
  message.
- **multiple subscribers** — two sockets on one tenant, `publish` → both receive.
- **tenant isolation** — sockets on tenant A and tenant B; `publish` to A reaches
  only A's sockets.
- **unsubscribe stops delivery** — subscribe then unsubscribe, `publish` → the
  socket receives nothing; the tenant entry is pruned (`tenant_id not in
  registry._subscribers`).
- **dead socket suppressed** — one failing socket and one healthy socket on a
  tenant; `publish` → the healthy one still receives, no exception propagates.
- **no subscribers** — `publish` to a tenant with no entry is a silent no-op.
- **snapshot safety** — a fake socket whose `send_data` subscribes a *new* socket
  to the same tenant mid-publish does not raise (proves `publish` iterates a
  snapshot, not the live set).

The connect/disconnect path through the real registry is already exercised by
#36's `tests/sync/test_ws_handshake.py` happy-path tests (the app now wires
`InMemorySubscriberRegistry`); the `_SpyRegistry`-injected seam test there
continues to assert `subscribe`/`unsubscribe` are called.

## Out of scope (later issues)

- Calling `publish` from the event-accept path (the fan-out hook) — #38 (M3.3).
- Resume-from-cursor before live delivery — #39 (M3.4).
- Cross-process / durable distribution and any multi-process ADR — deferred by
  ADR-013; not part of M3.
