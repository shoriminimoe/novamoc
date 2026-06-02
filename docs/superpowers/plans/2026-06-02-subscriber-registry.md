# M3.2 In-memory Subscriber Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `NoopSubscriberRegistry` placeholder with a working `InMemorySubscriberRegistry` (`dict[tenant_id, set[WebSocket]]`) that fans a pre-encoded message out to a tenant's connected sockets.

**Architecture:** Add the concrete registry beside the existing `SubscriberRegistry` Protocol in `domain/sync/_registry.py`, unit-test it directly with a fake socket, then swap it into `asgi.create_app` in place of the no-op. The Protocol seam means the controller is untouched. `publish` snapshots the tenant's socket set before awaiting any send (single event loop, no lock) and suppresses per-socket send failures.

**Tech Stack:** Python 3.14, Litestar (`WebSocket`, `WebSocketException`), pytest (asyncio auto mode — no `@pytest.mark.asyncio` needed).

**Spec:** `docs/superpowers/specs/2026-06-02-subscriber-registry-design.md`

---

## Orientation (read before starting)

- The `SubscriberRegistry` Protocol already exists in `src/py/novamoc/domain/sync/_registry.py` with `subscribe(tenant_id, socket)` / `unsubscribe(tenant_id, socket)` / `publish(tenant_id, message: bytes)`, all `async`. The Protocol is `@runtime_checkable` — **keep that decorator**; Litestar isinstance-checks the DI-injected registry against it, and removing it breaks WS dependency injection (there is a comment in the file saying so).
- `NoopSubscriberRegistry` is the current placeholder in the same file. `asgi.create_app` constructs it: `src/py/novamoc/asgi.py` has `from novamoc.domain.sync import NoopSubscriberRegistry, SyncController` (in the deferred-import block) and `subscriber_registry = NoopSubscriberRegistry()`, then puts it on `State` under `"subscriber_registry"`.
- `src/py/novamoc/domain/sync/__init__.py` re-exports `NoopSubscriberRegistry`, `SubscriberRegistry`, `SyncController` in `__all__`.
- `WebSocket` is hashable (identity-based — it does not override `__eq__`), so `set[WebSocket]` works.
- `WebSocket.send_data(data: str | bytes, mode="text")` decodes `bytes` to a UTF-8 text frame.
- `tests/sync/test_registry.py` currently holds one test, `test_noop_registry_methods_are_no_ops`. pytest runs in asyncio auto mode, so `async def test_...` needs no marker.
- Run commands from the repo root. Test shape: `uv run pytest <path> -v`. Full gate: `just check`. The JS steps of `just check` (`typecheck-js`, `coverage-js`) fail in this environment because frontend deps aren't installed (`svelte-kit: not found`) — that is pre-existing and unrelated; verify the Python side with `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `just coverage-py`, and the ruff portion of `just ratchet`.
- Python line-coverage ratchet floor is **97%** and branch floor **87%** — both are tight; keep new code covered.

---

## File structure

**Modify:**
- `src/py/novamoc/domain/sync/_registry.py` — add `InMemorySubscriberRegistry` (Task 1), remove `NoopSubscriberRegistry` (Task 2).
- `src/py/novamoc/domain/sync/__init__.py` — swap the export `NoopSubscriberRegistry` → `InMemorySubscriberRegistry` (Task 2).
- `src/py/novamoc/asgi.py` — construct `InMemorySubscriberRegistry()` (Task 2).
- `tests/sync/test_registry.py` — add `InMemorySubscriberRegistry` unit tests (Task 1); drop the no-op test (Task 2).

---

## Task 1: Implement `InMemorySubscriberRegistry` with unit tests

The no-op stays in place this task (still wired in `asgi`), so the suite remains green; we only *add* the new class and its tests.

**Files:**
- Modify: `src/py/novamoc/domain/sync/_registry.py`
- Test: `tests/sync/test_registry.py`

- [ ] **Step 1: Write the failing "deliver" test + fake socket**

Replace the entire contents of `tests/sync/test_registry.py` with:

```python
from __future__ import annotations

import uuid

from litestar.exceptions import WebSocketException

from novamoc.domain.sync._registry import (
    InMemorySubscriberRegistry,
    NoopSubscriberRegistry,
)


class _FakeSocket:
    """Records send_data calls; optionally fails to simulate a dead peer.

    May run an on_send hook to exercise mid-publish mutation.
    """

    def __init__(self, *, fail: bool = False, on_send=None) -> None:
        self.sent: list[bytes] = []
        self._fail = fail
        self._on_send = on_send

    async def send_data(self, data: bytes, mode: str = "text") -> None:
        if self._on_send is not None:
            self._on_send()
        if self._fail:
            raise WebSocketException("boom")
        self.sent.append(data)


async def test_publish_delivers_to_subscriber() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    sock = _FakeSocket()
    await reg.subscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"hello")
    assert sock.sent == [b"hello"]


async def test_publish_reaches_all_subscribers_of_a_tenant() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    a, b = _FakeSocket(), _FakeSocket()
    await reg.subscribe(tid, a)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid, b)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")
    assert a.sent == [b"x"]
    assert b.sent == [b"x"]


async def test_publish_is_tenant_scoped() -> None:
    reg = InMemorySubscriberRegistry()
    tid_a, tid_b = uuid.uuid4(), uuid.uuid4()
    a, b = _FakeSocket(), _FakeSocket()
    await reg.subscribe(tid_a, a)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid_b, b)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid_a, b"only-a")
    assert a.sent == [b"only-a"]
    assert b.sent == []


async def test_unsubscribe_stops_delivery_and_prunes() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    sock = _FakeSocket()
    await reg.subscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.unsubscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")
    assert sock.sent == []
    assert tid not in reg._subscribers


async def test_publish_suppresses_a_dead_socket() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    dead, alive = _FakeSocket(fail=True), _FakeSocket()
    await reg.subscribe(tid, dead)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid, alive)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")  # must not raise
    assert alive.sent == [b"x"]


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    reg = InMemorySubscriberRegistry()
    await reg.publish(uuid.uuid4(), b"x")  # must not raise


async def test_unsubscribe_unknown_tenant_is_a_noop() -> None:
    reg = InMemorySubscriberRegistry()
    sock = _FakeSocket()
    # Must not raise.
    await reg.unsubscribe(uuid.uuid4(), sock)  # ty: ignore[invalid-argument-type]


async def test_publish_iterates_a_snapshot() -> None:
    # A socket that subscribes a new peer mid-send must not trip a
    # "set changed during iteration" error — publish iterates a copy.
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    late = _FakeSocket()
    first = _FakeSocket(on_send=lambda: reg._subscribers[tid].add(late))
    await reg.subscribe(tid, first)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")  # must not raise
    assert first.sent == [b"x"]


async def test_noop_registry_methods_are_no_ops() -> None:
    reg = NoopSubscriberRegistry()
    tid = uuid.uuid4()
    await reg.subscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.unsubscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"payload")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/sync/test_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'InMemorySubscriberRegistry'` (the no-op test would pass, but the import error fails collection of the whole module).

- [ ] **Step 3: Implement `InMemorySubscriberRegistry`**

In `src/py/novamoc/domain/sync/_registry.py`, add the runtime imports at the top of the import block (after `from __future__ import annotations`):

```python
import contextlib

from litestar.exceptions import WebSocketException
```

Then add the class after `NoopSubscriberRegistry` (keep the Protocol and the no-op as they are):

```python
class InMemorySubscriberRegistry:
    """Per-process tenant → connected-sockets map (ADR-013).

    Single event loop: subscribe/unsubscribe mutate without awaiting, so
    they are atomic relative to publish; publish snapshots the set before
    awaiting any send.
    """

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[WebSocket]] = {}

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
            # Best-effort: a closed peer must not abort fan-out to the rest;
            # its own handler's unsubscribe removes it.
            with contextlib.suppress(WebSocketException, RuntimeError):
                await socket.send_data(message, mode="text")
```

Note: `uuid` and `WebSocket` are already imported under `if TYPE_CHECKING:` in this file and are used here only in annotations (lazy under `from __future__ import annotations`), so they stay where they are — do **not** move them to runtime.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/sync/test_registry.py -v`
Expected: PASS (all nine).

- [ ] **Step 5: Lint and type-check the touched files**

Run: `uv run ruff check src/py/novamoc/domain/sync/_registry.py tests/sync/test_registry.py && uv run ruff format src/py/novamoc/domain/sync/_registry.py tests/sync/test_registry.py && uv run ty check`
Expected: all clean. If ruff flags the lambda in `test_publish_iterates_a_snapshot` (E731 is for assignments, not args — should be fine) or anything else, resolve per the repo ratchet workflow (read the rule; prefer a fix; scoped `# noqa` with rationale only as last resort).

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/sync/_registry.py tests/sync/test_registry.py
git commit -m "feat(sync): in-memory subscriber registry (#37)"
```

---

## Task 2: Swap the no-op for the real registry

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `src/py/novamoc/domain/sync/__init__.py`
- Modify: `src/py/novamoc/domain/sync/_registry.py` (remove the no-op)
- Modify: `tests/sync/test_registry.py` (remove the no-op test)

- [ ] **Step 1: Point `asgi.create_app` at the real registry**

In `src/py/novamoc/asgi.py`, change the deferred import line

```python
    from novamoc.domain.sync import NoopSubscriberRegistry, SyncController
```
to
```python
    from novamoc.domain.sync import InMemorySubscriberRegistry, SyncController
```

and change the construction line

```python
    subscriber_registry = NoopSubscriberRegistry()
```
to
```python
    subscriber_registry = InMemorySubscriberRegistry()
```

(Leave the `State` wiring and everything else unchanged.)

- [ ] **Step 2: Update the package exports**

In `src/py/novamoc/domain/sync/__init__.py`, replace `NoopSubscriberRegistry` with `InMemorySubscriberRegistry` in both the import and `__all__`. The file should read:

```python
"""Real-time sync WebSocket transport (ADR-013)."""

from __future__ import annotations

from novamoc.domain.sync._registry import (
    InMemorySubscriberRegistry,
    SubscriberRegistry,
)
from novamoc.domain.sync.controllers import SyncController

__all__ = ("InMemorySubscriberRegistry", "SubscriberRegistry", "SyncController")
```

- [ ] **Step 3: Remove the no-op class and its test**

In `src/py/novamoc/domain/sync/_registry.py`, delete the entire `NoopSubscriberRegistry` class (the Protocol and `InMemorySubscriberRegistry` stay).

In `tests/sync/test_registry.py`, delete the `test_noop_registry_methods_are_no_ops` function and drop `NoopSubscriberRegistry` from the import (`from novamoc.domain.sync._registry import InMemorySubscriberRegistry`).

- [ ] **Step 4: Run the full Python suite**

Run: `uv run pytest -q`
Expected: PASS. The `tests/sync/test_ws_handshake.py` happy-path tests now exercise the real `InMemorySubscriberRegistry` (subscribe on connect, unsubscribe on disconnect); the `_SpyRegistry`-injected seam test overrides `app.state.subscriber_registry`, so it is unaffected.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/py/novamoc tests && uv run ruff format --check src/py/novamoc tests && uv run ty check`
Expected: all clean. (If ruff reports `NoopSubscriberRegistry` is now an undefined/unused reference anywhere, you missed an edit — grep `rg NoopSubscriberRegistry` should return nothing.)

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/asgi.py src/py/novamoc/domain/sync/__init__.py src/py/novamoc/domain/sync/_registry.py tests/sync/test_registry.py
git commit -m "refactor(sync): wire InMemorySubscriberRegistry, drop the no-op (#37)"
```

---

## Task 3: Full gate

**Files:** possibly `.ruff-ratchet.json` (only if a count legitimately dropped).

- [ ] **Step 1: Coverage**

Run: `just coverage-py`
Expected: full suite green. Confirm `domain/sync/_registry.py` shows high coverage and the overall `TOTAL` line stays at ≥ 97% line / ≥ 87% branch (the ratchet floors). The new registry code is fully exercised by Task 1's tests, so this should hold.

- [ ] **Step 2: Ratchet (ruff portion)**

Run: `uv run python scripts/ratchet.py`
Expected: `ruff ratchet ... Ratchet OK: baseline matches.` (The coverage sub-check needs the JS `coverage-summary.json` and will error in this environment — that is the pre-existing JS-toolchain gap; the ruff ratchet line is the one that matters for this Python change.) If the ruff ratchet reports counts *decreased*, run `just ratchet-update` and stage `.ruff-ratchet.json`. Do not bump any baseline upward.

- [ ] **Step 3: DB drift check (no models changed, so a sanity check)**

This change adds no models, so there is no migration drift. No action needed unless `git diff` shows a change under `db/models/` — it should not.

- [ ] **Step 4: Final sync-suite run**

Run: `uv run pytest tests/sync/ -v`
Expected: all green (registry unit tests + handshake e2e).

- [ ] **Step 5: Commit any ratchet follow-up**

```bash
git add -A
git commit -m "chore(sync): ratchet follow-up for M3.2 (#37)"
```

(Skip this commit if nothing changed.)

---

## Self-review notes (planner)

- **Spec coverage:** `InMemorySubscriberRegistry` location/shape → Task 1 Step 3; `dict[tenant_id, set[WebSocket]]` state → Step 3; subscribe/unsubscribe/publish bodies (incl. pruning, snapshot, suppression) → Step 3 + tests in Step 1; concurrency (no lock) → embedded in the snapshot design and the snapshot test; send mode (`send_data(..., mode="text")`) → Step 3 + delivery tests; best-effort error handling → dead-socket test; remove Noop + wire asgi → Task 2; all eight spec test cases (deliver, multiple, isolation, unsubscribe+prune, dead-socket, no-subscribers, snapshot — plus unknown-tenant unsubscribe) → Task 1 Step 1. No gaps.
- **No DB:** registry touches no database; unit tests use a fake socket, which is correct here (the "no DB mocks" rule is about the storage layer, not this in-memory router).
- **Type/name consistency:** `InMemorySubscriberRegistry`, `_subscribers`, `subscribe`/`unsubscribe`/`publish(tenant_id, message: bytes)`, `send_data(message, mode="text")` are used identically across the implementation, the asgi wiring, the exports, and the tests.
- **Greenness:** Task 1 leaves the no-op wired (suite green); Task 2 swaps and removes it in one commit (suite green). No broken intermediate state.
- **Out of scope:** `publish` caller / fan-out hook (#38), resume (#39), durable/cross-process distribution (deferred by ADR-013).
```
