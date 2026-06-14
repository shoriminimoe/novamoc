# M3.3 Event Broadcaster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fan out accepted data events to connected WebSocket subscribers via a signal-driven background `EventBroadcaster` that tails `event_log`.

**Architecture:** A long-lived `EventBroadcaster` task tails `event_log` through `EventLogService` (cross-tenant via the `SKIP_TENANT_FILTER` hatch), encoding each new row to a `RecordedEvent` and publishing it to the per-tenant `SubscriberRegistry`. The accept path only sets a flag; an `after_response` hook fires a non-blocking `asyncio.Event` signal post-commit. The broadcaster reads only committed rows, so a rolled-back batch is never fanned out.

**Tech Stack:** Python 3.14, Litestar (lifespan `on_startup`/`on_shutdown`, controller `after_response`), advanced-alchemy (`EventLogService`), msgspec, asyncio, pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-06-05-event-broadcaster-design.md`

---

## Orientation (read before starting)

- `RecordedEvent` (`domain/events/_payloads.py:190`) is the read-side wire struct; `_row_to_recorded_event(row)` (`domain/events/_pagination.py:29`) maps an `EventLog` row to it (used by the catch-up paginator).
- `EventLogService` (`domain/events/services.py`) wraps `event_log`. `current_seq()` already does a raw `MAX(seq)` aggregate via `self.repository.session.execute(stmt)` — tenant-scoped by Layer 1. The new cross-tenant readers mirror that shape with `.execution_options(...)`.
- `SKIP_TENANT_FILTER = "novamoc_skip_tenant_filter"` (`db/_tenant_context.py`) is the execution-option key that suppresses Layer 1 / Layer 3 scoping. Apply with `stmt.execution_options(**{SKIP_TENANT_FILTER: True})`.
- A valid `EventLog` row that round-trips through `_row_to_recorded_event`: `op=EventOp.DELETE, value_json=None` reconstructs to a `Deactivated()` body (`body_from_row`, `_bundle.py`). Use that for seeding — it needs no field/value shape.
- `event_log.seq` is a global autoincrement; `received_at` is `server_default=func.now()` and is populated on the instance after `create()`/flush (SQLAlchemy uses RETURNING).
- Litestar lifecycle order is `handler → before_send (advanced-alchemy autocommit commits on 2xx) → after_response` (verified). So an `after_response` hook is strictly post-commit.
- A controller `after_response` hook is called with `(request)` (no `self`). Assign it as `after_response = staticmethod(_hook)`.
- asgi (`asgi.create_app`) builds singletons before the `Litestar(...)` call and puts them on `State(...)`; `subscriber_registry` and the alchemy config `cfg` are already in scope there. `on_startup=[_assert_alembic_at_head]` today. Imports inside `create_app` are deferred (`# ruff: noqa: PLC0415` at top of file).
- The conftest `settings` fixture builds `app=AppSettings(docs_base_url="http://test")`; the `app`/`client` fixtures call `create_app`. `EventOp` is importable from `novamoc.db.models.data`.
- JS steps of `just check` fail in this env (`svelte-kit: not found`) — pre-existing, unrelated. Verify the Python side: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `just coverage-py`, ruff portion of `just ratchet`. Python coverage floor is **97% line / 87% branch** — keep new code covered.

---

## File structure

**Create:**
- `src/py/novamoc/domain/events/_broadcaster.py` — the `EventBroadcaster`.
- `tests/events/test_broadcaster.py` — broadcaster unit tests.
- `tests/events/test_fanout_e2e.py` — accept-path notify + full-chain delivery + lifecycle tests.

**Modify:**
- `src/py/novamoc/domain/events/_payloads.py` — tag `RecordedEvent`.
- `src/py/novamoc/domain/events/services.py` — two cross-tenant readers.
- `src/py/novamoc/config.py` — `broadcaster_batch_size`, `broadcaster_enabled`.
- `src/py/novamoc/asgi.py` — build/wire the broadcaster + lifecycle.
- `src/py/novamoc/domain/events/controllers/_events.py` — accept-path flag + `after_response`.
- `tests/conftest.py` — disable the broadcaster loop in the general test settings.
- existing catch-up tests — expect the new `"type":"event"` field.

---

## Task 1: Tag `RecordedEvent` as `type="event"`

**Files:**
- Modify: `src/py/novamoc/domain/events/_payloads.py` (`RecordedEvent`, line ~190)
- Modify: existing catch-up tests that assert `RecordedEvent` dicts

- [ ] **Step 1: Write a failing test for the tag**

Append to `tests/events/test_pagination.py` (or create `tests/events/test_recorded_event_tag.py` if you prefer isolation):

```python
def test_recorded_event_encodes_type_tag() -> None:
    import datetime
    import uuid

    import msgspec

    from novamoc.domain.events._payloads import Activated, EntityFamily, RecordedEvent

    rec = RecordedEvent(
        seq=1,
        schema_version=1,
        hlc="hlc-1",
        family=EntityFamily.ASSET,
        type_id=uuid.uuid4(),
        instance_id=uuid.uuid4(),
        body=Activated(),
        received_at=datetime.datetime.now(datetime.UTC),
    )
    decoded = msgspec.json.decode(msgspec.json.encode(rec))
    assert decoded["type"] == "event"
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `uv run pytest tests/events/test_pagination.py -k recorded_event_encodes_type_tag -v`
Expected: FAIL — encoded dict has no `"type"` key (KeyError on `decoded["type"]`).

- [ ] **Step 3: Add the tag**

In `_payloads.py`, change the `RecordedEvent` class header:

```python
class RecordedEvent(
    msgspec.Struct, forbid_unknown_fields=True, tag_field="type", tag="event"
):
```

(Leave the body/fields unchanged. The nested `body: EventBody` keeps its own `tag_field="event"` — a different field at a different level, no collision.)

- [ ] **Step 4: Run the new test — expect PASS**

Run: `uv run pytest tests/events/test_pagination.py -k recorded_event_encodes_type_tag -v`
Expected: PASS.

- [ ] **Step 5: Update the catch-up tests for the new field**

Run the events suite: `uv run pytest tests/events/ -q`. Tests that assert exact `RecordedEvent` dicts (catch-up endpoint, pagination) now fail with an unexpected `"type":"event"` key. For each failing assertion, add `"type": "event"` to the expected dict (it sorts first as msgspec emits the tag field first). Re-run until `tests/events/` is green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/events/_payloads.py tests/events/
git commit -m "feat(events): tag RecordedEvent as type=event for self-describing frames (#38)"
```

---

## Task 2: `EventLogService` cross-tenant readers

**Files:**
- Modify: `src/py/novamoc/domain/events/services.py`
- Test: `tests/events/test_event_log_service.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_event_log_service.py`:

```python
from __future__ import annotations

import uuid

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events.services import EventLogService
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B


async def _insert(session, tenant_id) -> EventLog:
    row = EventLog(
        tenant_id=tenant_id,
        hlc=f"hlc-{uuid.uuid4()}",
        schema_version=1,
        table_name="assets",
        type_id=str(uuid.uuid4()),
        entity_id=str(uuid.uuid4()),
        op=EventOp.DELETE,
        value_json=None,
    )
    with use_tenant(tenant_id):
        session.add(row)
        await session.flush()
    return row


async def test_current_seq_all_tenants_is_global(session) -> None:
    await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    assert await svc.current_seq_all_tenants() == b.seq  # global max, latest insert


async def test_current_seq_all_tenants_zero_when_empty(session) -> None:
    svc = EventLogService(session=session)
    assert await svc.current_seq_all_tenants() == 0


async def test_list_after_all_tenants_crosses_tenants_in_seq_order(session) -> None:
    a = await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    rows = await svc.list_after_all_tenants(0, 10)
    assert [r.seq for r in rows] == [a.seq, b.seq]
    assert {r.tenant_id for r in rows} == {DEV_TENANT_ID_A, DEV_TENANT_ID_B}


async def test_list_after_all_tenants_respects_after_and_limit(session) -> None:
    a = await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    after_a = await svc.list_after_all_tenants(a.seq, 10)
    assert [r.seq for r in after_a] == [b.seq]
    capped = await svc.list_after_all_tenants(0, 1)
    assert [r.seq for r in capped] == [a.seq]
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/events/test_event_log_service.py -v`
Expected: FAIL — `AttributeError: 'EventLogService' object has no attribute 'current_seq_all_tenants'`.

- [ ] **Step 3: Implement the readers**

In `src/py/novamoc/domain/events/services.py`, add the import and two methods:

```python
from novamoc.db._tenant_context import SKIP_TENANT_FILTER
```

Add inside `EventLogService` (after `current_seq`):

```python
    async def current_seq_all_tenants(self) -> int:
        """Global ``MAX(event_log.seq)`` across every tenant (or 0).

        Cross-tenant: uses the ``SKIP_TENANT_FILTER`` escape hatch, for the
        broadcaster's start-at-tip. The ``_all_tenants`` suffix flags the
        deliberate cross-tenant read.
        """
        stmt = select(func.coalesce(func.max(EventLog.seq), 0)).execution_options(
            **{SKIP_TENANT_FILTER: True}
        )
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())

    async def list_after_all_tenants(self, after_seq: int, limit: int) -> list[EventLog]:
        """Rows with ``seq > after_seq`` across every tenant, ascending, capped
        at ``limit``.

        Cross-tenant (``SKIP_TENANT_FILTER``), for the broadcaster's drain.
        """
        stmt = (
            select(EventLog)
            .where(EventLog.seq > after_seq)
            .order_by(EventLog.seq)
            .limit(limit)
            .execution_options(**{SKIP_TENANT_FILTER: True})
        )
        result = await self.repository.session.execute(stmt)
        return list(result.scalars().all())
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/events/test_event_log_service.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/events/services.py tests/events/test_event_log_service.py && uv run ty check`
Expected: clean. (Resolve any finding per the ratchet workflow.)

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/events/services.py tests/events/test_event_log_service.py
git commit -m "feat(events): cross-tenant EventLogService readers for the broadcaster (#38)"
```

---

## Task 3: Broadcaster config settings

**Files:**
- Modify: `src/py/novamoc/config.py` (`AppSettings`)
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to the `TestAppSettings` class in `tests/test_config.py`:

```python
    def test_broadcaster_batch_size_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_BROADCASTER_BATCH_SIZE", raising=False)
        assert AppSettings().broadcaster_batch_size == 500

    def test_broadcaster_enabled_default_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_BROADCASTER_ENABLED", raising=False)
        assert AppSettings().broadcaster_enabled is True

    def test_broadcaster_enabled_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_BROADCASTER_ENABLED", "false")
        assert AppSettings().broadcaster_enabled is False
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_config.py -k broadcaster -v`
Expected: FAIL — attributes don't exist.

- [ ] **Step 3: Add the fields**

In `src/py/novamoc/config.py`, inside `AppSettings`, add:

```python
    broadcaster_batch_size: int = field(
        default_factory=_int_env("NOVAMOC_BROADCASTER_BATCH_SIZE", 500)
    )
    broadcaster_enabled: bool = field(
        default_factory=_bool_env("NOVAMOC_BROADCASTER_ENABLED", True)
    )
```

Extend the `AppSettings` docstring `Attributes:` block:

```
        broadcaster_batch_size: Max event_log rows the fan-out broadcaster
            drains per query.
        broadcaster_enabled: Whether the background fan-out broadcaster loop
            runs. Production-safe default True; the test suite disables the
            loop and drives drain_once() directly for determinism.
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/test_config.py -k broadcaster -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): broadcaster_batch_size + broadcaster_enabled settings (#38)"
```

---

## Task 4: `EventBroadcaster`

**Files:**
- Create: `src/py/novamoc/domain/events/_broadcaster.py`
- Test: `tests/events/test_broadcaster.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_broadcaster.py`:

```python
from __future__ import annotations

import asyncio
import uuid

import msgspec
from advanced_alchemy.base import metadata_registry

from novamoc.db._tenant_context import use_tenant
from novamoc.db.config import build_alchemy_config
from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events._broadcaster import EventBroadcaster
from novamoc.domain.events._payloads import RecordedEvent
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B


class _StubRegistry:
    def __init__(self) -> None:
        self.published: list[tuple[uuid.UUID, bytes]] = []

    async def subscribe(self, tenant_id, socket) -> None: ...
    async def unsubscribe(self, tenant_id, socket) -> None: ...
    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        self.published.append((tenant_id, message))


async def _make_config(settings):
    cfg = build_alchemy_config(settings)
    engine = cfg.get_engine()
    async with engine.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    return cfg


async def _insert(cfg, tenant_id) -> int:
    async with cfg.get_session() as session, use_tenant(tenant_id):
        row = EventLog(
            tenant_id=tenant_id,
            hlc=f"hlc-{uuid.uuid4()}",
            schema_version=1,
            table_name="assets",
            type_id=str(uuid.uuid4()),
            entity_id=str(uuid.uuid4()),
            op=EventOp.DELETE,
            value_json=None,
        )
        session.add(row)
        await session.flush()
        seq = row.seq
        await session.commit()
    return seq


async def test_drain_delivers_each_row_to_its_tenant(settings) -> None:
    cfg = await _make_config(settings)
    seq_a = await _insert(cfg, DEV_TENANT_ID_A)
    seq_b = await _insert(cfg, DEV_TENANT_ID_B)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)

    drained = await bcast.drain_once()

    assert drained == 2
    assert [t for t, _ in reg.published] == [DEV_TENANT_ID_A, DEV_TENANT_ID_B]
    first = msgspec.json.decode(reg.published[0][1], type=RecordedEvent)
    assert first.seq == seq_a
    # second drain is empty (cursor advanced past seq_b)
    assert await bcast.drain_once() == 0
    await cfg.get_engine().dispose()


async def test_start_at_tip_skips_existing_then_delivers_new(settings) -> None:
    cfg = await _make_config(settings)
    await _insert(cfg, DEV_TENANT_ID_A)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)

    await bcast.start_at_tip()
    assert await bcast.drain_once() == 0  # already at tip

    await _insert(cfg, DEV_TENANT_ID_B)
    assert await bcast.drain_once() == 1
    assert reg.published[0][0] == DEV_TENANT_ID_B
    await cfg.get_engine().dispose()


async def test_drain_respects_batch_size(settings) -> None:
    cfg = await _make_config(settings)
    await _insert(cfg, DEV_TENANT_ID_A)
    await _insert(cfg, DEV_TENANT_ID_A)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=1)

    assert await bcast.drain_once() == 1
    assert await bcast.drain_once() == 1
    assert await bcast.drain_once() == 0
    await cfg.get_engine().dispose()


async def test_run_loop_drains_on_signal(settings) -> None:
    cfg = await _make_config(settings)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)
    task = asyncio.create_task(bcast.run())
    try:
        await _insert(cfg, DEV_TENANT_ID_A)
        bcast.notify()
        for _ in range(200):  # bounded wait
            if reg.published:
                break
            await asyncio.sleep(0.01)
        assert len(reg.published) == 1
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await cfg.get_engine().dispose()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/events/test_broadcaster.py -v`
Expected: FAIL — `ModuleNotFoundError: novamoc.domain.events._broadcaster`.

- [ ] **Step 3: Implement the broadcaster**

Create `src/py/novamoc/domain/events/_broadcaster.py`:

```python
"""Background fan-out broadcaster (ADR-013).

Tails ``event_log`` and publishes each new row to the per-tenant
:class:`SubscriberRegistry`. Decoupled from the request lifecycle: the
accept path only fires a non-blocking signal post-commit; all DB reads,
encoding, and per-socket sends happen here. Reads only committed rows, so
a rolled-back batch is never fanned out.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import msgspec

from novamoc.domain.events._pagination import _row_to_recorded_event
from novamoc.domain.events.services import EventLogService

if TYPE_CHECKING:
    from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

    from novamoc.domain.sync._registry import SubscriberRegistry

_logger = logging.getLogger(__name__)


class EventBroadcaster:
    def __init__(
        self,
        registry: SubscriberRegistry,
        alchemy_config: SQLAlchemyAsyncConfig,
        *,
        batch_size: int,
    ) -> None:
        self._registry = registry
        self._alchemy_config = alchemy_config
        self._batch_size = batch_size
        self._last_seq = 0
        self._wake = asyncio.Event()

    async def start_at_tip(self) -> None:
        async with self._alchemy_config.get_session() as session:
            self._last_seq = await EventLogService(
                session=session
            ).current_seq_all_tenants()

    async def drain_once(self) -> int:
        async with self._alchemy_config.get_session() as session:
            rows = await EventLogService(session=session).list_after_all_tenants(
                self._last_seq, self._batch_size
            )
        for row in rows:
            payload = msgspec.json.encode(_row_to_recorded_event(row))
            await self._registry.publish(row.tenant_id, payload)
            self._last_seq = row.seq
        return len(rows)

    def notify(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()  # clear BEFORE draining: a notify mid-drain re-wakes us
            with contextlib.suppress(Exception):
                while await self.drain_once():
                    pass
```

Note on the `suppress(Exception)`: a transient drain failure must not kill the
loop; `_last_seq` only advances per successfully-published row, so the rows are
retried on the next signal. `CancelledError` is a `BaseException`, not caught by
`suppress(Exception)`, so cancellation still propagates for clean shutdown. Add a
log line inside the loop if you want the failure visible — but keep the suppress.

`uuid` and `SubscriberRegistry`/`SQLAlchemyAsyncConfig` are type-only here, so
they stay under `TYPE_CHECKING`.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/events/test_broadcaster.py -v`
Expected: PASS (all four, including the signal loop test).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/events/_broadcaster.py tests/events/test_broadcaster.py && uv run ty check`
Expected: clean. The bare `suppress(Exception)` may trip `BLE001`; if so, keep it with `# noqa: BLE001  # transient drain errors must not kill the loop` (a justified, scoped ignore — the loop is a long-lived background task that must survive one bad drain).

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/events/_broadcaster.py tests/events/test_broadcaster.py
git commit -m "feat(events): signal-driven EventBroadcaster (#38)"
```

---

## Task 5: Wire it in — lifecycle, accept-path flag, after_response

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `src/py/novamoc/domain/events/controllers/_events.py`
- Modify: `tests/conftest.py`
- Test: `tests/events/test_fanout_e2e.py` (create — notify wiring)

- [ ] **Step 1: Disable the loop in the test settings (keep the suite deterministic)**

In `tests/conftest.py`, the `settings` fixture builds `app=AppSettings(docs_base_url="http://test")`. Change it to:

```python
        app=AppSettings(docs_base_url="http://test", broadcaster_enabled=False),
```

(The broadcaster object is still built and put on state; only the background loop is gated off so tests drive `drain_once()` deterministically.)

- [ ] **Step 2: Add the accept-path flag + after_response hook**

In `src/py/novamoc/domain/events/controllers/_events.py`:

Add a module-level hook (near the other module-level helpers, after imports):

```python
async def _notify_broadcaster(request: Request) -> None:
    """Post-commit fan-out signal. ``after_response`` runs after the
    autocommit ``before_send`` commit, so the accepted rows are committed
    and visible to the broadcaster's next drain. No DB or fan-out work here
    — just the signal."""
    if getattr(request.state, "broadcaster_notify", False):
        request.app.state.event_broadcaster.notify()
```

On the `EventsController` class, add the attribute (alongside `path`/`tags`/`dependencies`):

```python
    after_response = staticmethod(_notify_broadcaster)
```

In the `append` handler, just before `return EventBatchResponse(...)`, set the flag when anything was accepted:

```python
        if any(o.outcome == "accepted" for o in outcomes):
            request.state.broadcaster_notify = True
        return EventBatchResponse(outcomes=tuple(outcomes))
```

(`request: Request` is already a parameter of `append`. `Request` is already imported in this module.)

- [ ] **Step 3: Build + wire the broadcaster in `asgi.create_app`**

In `src/py/novamoc/asgi.py`, add to the deferred imports inside `create_app`:

```python
    import asyncio
    import contextlib

    from novamoc.domain.events._broadcaster import EventBroadcaster
```

After `subscriber_registry = InMemorySubscriberRegistry()`, add:

```python
    event_broadcaster = EventBroadcaster(
        subscriber_registry, cfg, batch_size=s.app.broadcaster_batch_size
    )

    async def _start_broadcaster(app: Litestar) -> None:
        if not s.app.broadcaster_enabled:
            return
        await event_broadcaster.start_at_tip()
        app.state.broadcaster_task = asyncio.create_task(event_broadcaster.run())

    async def _stop_broadcaster(app: Litestar) -> None:
        task = app.state.get("broadcaster_task")
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```

Add `"event_broadcaster": event_broadcaster` to the `State({...})` dict.

Change the lifecycle args of the `Litestar(...)` call:

```python
        on_startup=[_assert_alembic_at_head, _start_broadcaster],
        on_shutdown=[_stop_broadcaster],
```

- [ ] **Step 4: Write the notify-wiring e2e test**

Create `tests/events/test_fanout_e2e.py`. It reuses the existing
`tests/events/_http_helpers.py` (`create_asset_type` → `(type_id,
schema_version)`; `create_asset` POSTs a valid accepted `created` event and
asserts 202; `event_envelope` builds a wire event dict):

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from tests.events._http_helpers import (
    DEFAULT_HLC,
    create_asset,
    create_asset_type,
    event_envelope,
)

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


class _StubBroadcaster:
    def __init__(self) -> None:
        self.notified = 0

    def notify(self) -> None:
        self.notified += 1


async def test_accepted_batch_signals_broadcaster(
    client: AsyncTestClient, app: Litestar
) -> None:
    stub = _StubBroadcaster()
    app.state.event_broadcaster = stub
    type_id, schema_version = await create_asset_type(client)
    await create_asset(
        client, type_id=type_id, schema_version=schema_version, hlc=DEFAULT_HLC
    )  # asserts 202 (accepted) internally
    assert stub.notified == 1


async def test_rejected_batch_does_not_signal(
    client: AsyncTestClient, app: Litestar
) -> None:
    stub = _StubBroadcaster()
    app.state.event_broadcaster = stub
    type_id, schema_version = await create_asset_type(client)
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version + 1,  # != current → batch rejected
            "events": [event_envelope(type_id=type_id)],
        },
    )
    assert resp.status_code == 409, resp.text  # schema_version_stale (batch-level)
    assert stub.notified == 0
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. The general suite has `broadcaster_enabled=False`, so no background loop runs; the notify-wiring tests use the stubbed broadcaster on `app.state`.

- [ ] **Step 6: Lint + type-check**

Run: `uv run ruff check src/py/novamoc tests && uv run ruff format --check src/py/novamoc tests && uv run ty check`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/asgi.py src/py/novamoc/domain/events/controllers/_events.py tests/conftest.py tests/events/test_fanout_e2e.py
git commit -m "feat(events): wire broadcaster lifecycle + post-commit fan-out signal (#38)"
```

---

## Task 6: Full-chain delivery + lifecycle coverage + gate

**Files:**
- Modify: `tests/events/test_fanout_e2e.py` (append)
- Possibly: `.ruff-ratchet.json`

- [ ] **Step 1: Full-chain delivery test (deterministic, manual drain)**

Append to `tests/events/test_fanout_e2e.py` (add `from tests._constants import
DEV_TENANT_ID` to the imports). Connect a WS subscriber, POST a valid event,
drive `drain_once()` directly (the loop is disabled in tests), and assert the
socket receives the `{"type":"event",...}` frame:

```python
async def test_event_reaches_subscribed_socket(
    client: AsyncTestClient, app: Litestar
) -> None:
    type_id, schema_version = await create_asset_type(client)
    with await client.websocket_connect("/sync/live") as ws:
        ws.send_json({"type": "hello", "tenant_id": str(DEV_TENANT_ID), "cursor": 0})
        assert ws.receive_json()["type"] == "welcome"

        await create_asset(
            client, type_id=type_id, schema_version=schema_version, hlc=DEFAULT_HLC
        )
        drained = await app.state.event_broadcaster.drain_once()
        assert drained >= 1

        frame = ws.receive_json()
    assert frame["type"] == "event"
    assert frame["body"]["event"] == "created"
```

Because the test's `app.state.event_broadcaster` is the real `EventBroadcaster`
(the loop is just not auto-started), `drain_once()` reads the committed event and
publishes to the live `InMemorySubscriberRegistry`, which sends to the connected
socket; the WS test session's `receive_json()` returns the frame. (Per-tenant
routing — that a *different* tenant's socket would not receive this — is already
proven by `test_drain_delivers_each_row_to_its_tenant` in Task 4, so it is not
re-tested here where a second authenticated tenant would add login boilerplate.)

The `create_asset` POST stays *inside* the `with ws:` block (the socket must be
subscribed before the event is published); the WS session and the HTTP client
share one portal, so nesting an `await client.post(...)` inside the block works.

- [ ] **Step 2: Lifecycle wiring coverage (loop enabled)**

Append a test that builds an app with `broadcaster_enabled=True` so the
`on_startup` create-task / `on_shutdown` cancel branches are covered. Mirror the
`app` fixture's construction but flip the setting (use `dataclasses.replace` on
the `settings` fixture and call `create_app`), enter an `AsyncTestClient`, and
assert the task exists:

```python
async def test_broadcaster_task_runs_when_enabled(settings, app) -> None:
    import asyncio
    from dataclasses import replace

    from litestar.testing import AsyncTestClient

    from novamoc.asgi import create_app
    from advanced_alchemy.extensions.litestar import (
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )

    # reuse the app fixture's already-migrated engine
    plugin = app.plugins.get(SQLAlchemyPlugin)
    cfg = next(c for c in plugin.config if isinstance(c, SQLAlchemyAsyncConfig))
    enabled = replace(settings, app=replace(settings.app, broadcaster_enabled=True))
    enabled_app = create_app(settings=enabled, alchemy_config=cfg)

    async with AsyncTestClient(enabled_app):
        task = enabled_app.state.get("broadcaster_task")
        assert isinstance(task, asyncio.Task)
        assert not task.done()
    # context exit triggers on_shutdown → the task is cancelled
    assert task.cancelled() or task.done()
```

- [ ] **Step 3: Run the fan-out e2e + full suite**

Run: `uv run pytest tests/events/test_fanout_e2e.py -v` then `uv run pytest -q`
Expected: all green. If the lifecycle test's enabled loop is flaky against the in-memory `StaticPool`, keep its scope minimal (it only asserts task existence/cancellation; it never POSTs, so the loop stays idle on `wait()` and never opens a competing session).

- [ ] **Step 4: Coverage**

Run: `just coverage-py`
Expected: full suite green; `domain/events/_broadcaster.py` and the new service readers well-covered; overall `TOTAL` ≥ 97% line / ≥ 87% branch. If line coverage dips below 97% because of an uncovered branch (e.g. the `_stop_broadcaster` early-return when no task), add a targeted test or confirm the lifecycle test covers it.

- [ ] **Step 5: Ratchet + final lint/type**

Run: `uv run python scripts/ratchet.py` (ruff portion must say `Ratchet OK`), `uv run ruff check src/py/novamoc tests`, `uv run ty check`.
Expected: clean. If ruff counts dropped, `just ratchet-update` and stage `.ruff-ratchet.json`; never bump a baseline up.

- [ ] **Step 6: Commit**

```bash
git add tests/events/test_fanout_e2e.py
git commit -m "test(events): full-chain fan-out delivery + broadcaster lifecycle (#38)"
```

---

## Self-review notes (planner)

- **Spec coverage:** RecordedEvent tag + catch-up ripple → Task 1; cross-tenant service readers (SKIP_TENANT_FILTER) → Task 2; config (batch size + enabled gate) → Task 3; EventBroadcaster (start_at_tip, drain_once, notify, run, error-contained) → Task 4; lifecycle wiring + accept flag + after_response signal → Task 5; strict "rolled-back never fans out" → structural (broadcaster reads committed rows; the rejected-batch test in Task 5 + the per-tenant drain test confirm); full-chain delivery + lifecycle coverage → Task 6. No gaps.
- **Determinism:** the background loop is gated off (`broadcaster_enabled=False`) for the general suite; broadcaster behavior is proven via direct `drain_once()`/`run()`+signal tests and a manual-drain full-chain e2e — no reliance on loop timing for assertions except the one bounded-wait signal test (Task 4) and the idle-loop lifecycle test (Task 6).
- **No DB mocks:** every broadcaster/service test runs against a real in-memory engine; only the *registry* (fan-out target) and the *broadcaster* (in the notify-wiring test) are stubbed, which is correct — those are not the storage layer.
- **Type/name consistency:** `current_seq_all_tenants` / `list_after_all_tenants(after_seq, limit)`, `EventBroadcaster(registry, alchemy_config, *, batch_size)` with `.start_at_tip()` / `.drain_once()` / `.notify()` / `.run()`, `event_broadcaster` state key, `broadcaster_notify` request-state flag, and `broadcaster_enabled` / `broadcaster_batch_size` settings are used identically across tasks.
- **Two steps need the implementer to read existing helpers** (Task 5 Step 4, Task 6 Step 1) rather than hand-rolling the `EventBatch` body — this is deliberate: reuse `tests/events/_http_helpers.py` so the accepted-batch shape stays correct as the events wire format evolves. The expected outcome (202 + accepted, or 409 stale) is specified.
- **Out of scope:** per-subscriber gap-close/resume (#39), multi-process distribution (deferred by ADR-013), ADR-013 acceptance (#40).
```
