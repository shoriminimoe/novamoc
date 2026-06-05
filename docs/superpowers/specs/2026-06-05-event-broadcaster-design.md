# M3.3 — Signal-driven event broadcaster (fan-out on acceptance)

**Issue:** #38 (M3 — WebSocket transport and fan-out)
**Refs:** ADR-011 (append-only event log), ADR-013 (broadcast ordering: "a single broadcaster task reads new log entries in order and fans them out"), ADR-014/ADR-017 (tenant scoping).
**Depends on:** #24 (M1.5 accept path), #37 (M3.2 registry) — both merged.
**Status:** Approved, ready for implementation planning.

## Summary

Fan out accepted data events to connected WebSocket subscribers. Rather than a
callback bolted to the request lifecycle, this is a long-lived background
`EventBroadcaster` task (ADR-013's "single broadcaster task") that tails
`event_log` and publishes each new row to the subscriber registry. The request
path does almost nothing: the accept handler flags that it accepted events, and
an `after_response` hook fires a cheap non-blocking signal that wakes the
broadcaster. All fan-out work — the DB read, encoding, and per-socket sends —
happens in the background task, never on the request.

## Why a background broadcaster (not a request-coupled callback)

The issue text suggested "a dependency-injected callback on the events service."
We chose the ADR-013 broadcaster instead because it is cleaner and strictly
correct:

- **The accept path is unchanged** except one flag — no event capture, no
  `request.state` event payload, no post-commit DB work on the request.
- **"Rolled-back must not fan out" holds with no residual gap.** The broadcaster
  reads `event_log` in its *own* session, so it only ever sees *committed* rows.
  A rolled-back batch is structurally invisible to it. (A request-coupled
  after_response callback that captured events in-memory would still fan out in
  the pathological "2xx response but the outer commit itself threw" case;
  re-reading from the committed log removes that gap.)
- **Decoupled.** Fan-out latency, batching, and back-pressure are the
  broadcaster's concern, isolated from request handling.

## Signal, not polling

SQLite has no LISTEN/NOTIFY, so the broadcaster cannot be pushed by the database.
A busy poll loop wastes work when idle. Instead the broadcaster waits on an
`asyncio.Event`; the request path *signals* it post-commit. The signal is a
non-blocking `Event.set()` — it does no DB or fan-out work, so the heavy lifting
stays off the request lifecycle while latency stays low (immediate wake).

Correctness does not depend on the signal being reliable: the broadcaster always
drains *all* rows with `seq > _last_seq`, so a missed or spurious signal only
affects timing, never delivery. The signal is an optimization over polling, not
the correctness mechanism — `_last_seq` + drain-all-new is.

## Components

### 1. `RecordedEvent` gains a type tag (`_payloads.py`)

Add `tag_field="type", tag="event"` to the existing `RecordedEvent` struct. Live
WS frames share a stream with the tagged `welcome`/`pong` frames, so an event
frame must be self-describing. Per CLAUDE.md ("emit the same struct so the wire
format is transport-independent"), the same tagged struct is used on the live WS
and the catch-up HTTP endpoint.

**Ripple:** `GET /events` (catch-up) response items each gain a `"type":"event"`
field. The catch-up / pagination tests that assert exact `RecordedEvent` dicts
update accordingly. Pre-release — this wire change is acceptable.

### 2. `EventBroadcaster` (`domain/events/_broadcaster.py`)

Lives in the events domain (it tails `event_log`, an events-domain table, and
reuses the events encoder), depending only on the narrow `SubscriberRegistry`
Protocol from `domain/sync`.

State: the `SubscriberRegistry`, the `SQLAlchemyAsyncConfig` (to open its own
sessions, the documented non-request pattern — same helper `seed_dev_admin`
uses), `_last_seq: int`, and `_wake: asyncio.Event`.

```python
class EventBroadcaster:
    def __init__(self, registry: SubscriberRegistry, alchemy_config, *, batch_size: int) -> None:
        self._registry = registry
        self._alchemy_config = alchemy_config
        self._batch_size = batch_size
        self._last_seq = 0
        self._wake = asyncio.Event()

    async def start_at_tip(self) -> None:
        # MAX(seq) across all tenants; default 0 on an empty log.
        async with self._alchemy_config.get_session() as session:
            stmt = select(func.coalesce(func.max(EventLog.seq), 0)).execution_options(
                **{SKIP_TENANT_FILTER: True}
            )
            self._last_seq = int((await session.execute(stmt)).scalar_one())

    async def drain_once(self) -> int:
        async with self._alchemy_config.get_session() as session:
            stmt = (
                select(EventLog)
                .where(EventLog.seq > self._last_seq)
                .order_by(EventLog.seq)
                .limit(self._batch_size)
                .execution_options(**{SKIP_TENANT_FILTER: True})
            )
            rows = list((await session.execute(stmt)).scalars().all())
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
            while await self.drain_once():
                pass
```

Notes:
- `SKIP_TENANT_FILTER` is the execution-option key `"novamoc_skip_tenant_filter"`
  (`db/_tenant_context.py`), checked by Layer 1 and Layer 3 of `db/_listeners`.
  The broadcaster is the first production caller — a legitimate system-level
  cross-tenant reader, exactly what the escape hatch documents.
- The cross-tenant read returns each row's `tenant_id`; fan-out routes per row to
  that tenant's subscribers via `registry.publish(row.tenant_id, ...)`. The
  registry no-ops for tenants with no subscribers.
- `_row_to_recorded_event` is reused as-is from `domain/events/_pagination.py`
  (no move needed — the broadcaster reads rows, so there is no `_bundle` import
  cycle).
- `_last_seq` advances per row, so a partial batch (capped at `batch_size`) is
  resumed by the next `drain_once` (`run` loops until a drain returns 0).
- Each `drain_once` opens and closes a fresh session; rows are materialized
  (`list(...)`) before the session closes so the per-row publish loop does not
  hold the session across `await registry.publish`.

### 3. Lifecycle wiring (`asgi.create_app`)

Build `EventBroadcaster(subscriber_registry, alchemy_config, batch_size=...)` and
put it on `State` under `event_broadcaster`. Add:
- `on_startup`: `await broadcaster.start_at_tip()`, then
  `app.state.broadcaster_task = asyncio.create_task(broadcaster.run())`.
- `on_shutdown`: cancel `broadcaster_task` and await its cancellation (suppress
  `CancelledError`).

`batch_size` is a new `broadcaster_batch_size` setting in `config.py`
(`AppSettings`), defaulting to a sensible bound (e.g. 500). Production-safe
default; no env override needed for dev.

### 4. Accept-path flag + `after_response` signal (`EventsController`)

- In the `append` handler, after building outcomes, set
  `request.state.broadcaster_notify = True` iff at least one outcome is
  `accepted`. (One line; no event payload on state — the broadcaster re-reads
  from the log.)
- A module-level `after_response` hook on `EventsController` reads
  `getattr(request.state, "broadcaster_notify", False)`; if set, calls
  `request.app.state.event_broadcaster.notify()`. `after_response` runs strictly
  after the autocommit `before_send` commit (verified: lifecycle order is
  `handler → before_send(commit on 2xx) → after_response`), so by the time the
  signal fires the accepted rows are committed and visible to the broadcaster's
  next drain. The hook touches no database and does no fan-out — just the signal.
- The hook is scoped to the events controller; the flag gate means it is a no-op
  for `GET /events` (catch-up) and for all-rejected POST batches.

## Data flow

```
POST /events
  → handler accepts events (savepoint inserts), sets request.state.broadcaster_notify
  → returns 202
  → before_send: autocommit commits (2xx)
  → after_response: broadcaster.notify()  [Event.set(), no work]

EventBroadcaster.run()  [background task, separate session]
  → wakes on the signal
  → drain_once(): SELECT event_log WHERE seq > last_seq (cross-tenant)
  → per row: registry.publish(row.tenant_id, encode(RecordedEvent))
  → registry fans out to that tenant's subscribed sockets
```

## Error handling

- The broadcaster's `run()` loop must survive a `drain_once` failure: it wraps
  the drain in `try/except Exception` (re-raising `CancelledError` for clean
  shutdown), logs, and continues to the next wake. Because `_last_seq` advances
  only after each row's publish returns, a failed drain leaves `_last_seq` at the
  last successfully-published row, so the next drain resumes from there. One
  transient error therefore cannot kill the task; the rows are retried on the
  next signal. (Rows are well-formed — validated at accept — and
  `registry.publish` is best-effort per socket, so a *persistent* per-row failure
  is not an expected condition and is not specially handled; YAGNI.)
- `registry.publish` is already best-effort per socket (suppresses dead peers),
  so a closed subscriber does not break fan-out.
- The `after_response` signal is a bare `Event.set()` and cannot fail in a way
  that affects the (already-sent) response.

## Testing

The deterministic seam is `drain_once()` — tests drive it directly rather than
racing the background loop. Real in-memory SQLite, no DB mocks; a stub registry
records `publish(tenant_id, payload)` calls.

- **drain delivers per tenant** — seed `event_log` rows under two tenants;
  `drain_once()` publishes each row to its own `tenant_id` on the stub registry,
  with the payload decoding to the expected `RecordedEvent` (incl. `type:event`);
  `_last_seq` advances to the max; a second `drain_once()` returns 0 and publishes
  nothing.
- **start_at_tip skips history** — seed rows, `start_at_tip()`, then
  `drain_once()` publishes nothing (already at the tip); insert a new row →
  `drain_once()` publishes only the new one.
- **batch cap resumes** — with `batch_size=1` and two new rows, the first
  `drain_once()` returns 1 and the second returns 1, in `seq` order.
- **drain error is contained** — patch `drain_once` to raise once then succeed;
  start `run()` as a task, signal it, and assert the task is still alive and
  publishes on the subsequent (succeeding) drain — i.e. one transient drain
  failure does not kill the loop.
- **signal wakes the loop** — start `run()` as a task, `notify()` after seeding,
  and bounded-wait until the stub registry observes the publish; cancel the task.
- **accept-path wiring** — POST a valid batch with a stubbed broadcaster on
  `app.state`; assert `notify()` was called once. POST a stale-schema batch (409)
  or an all-duplicate batch; assert `notify()` was NOT called.
- **full chain e2e** — connect a WS subscriber (handshake), POST an event on the
  same tenant, `await broadcaster.drain_once()`, and assert the socket receives
  the `{"type":"event",...}` frame; a different tenant's subscriber receives
  nothing.
- **catch-up ripple** — update the existing `GET /events` tests to expect the new
  `"type":"event"` field on each item.

## Out of scope (later issues)

- Resume-from-cursor / gap-close for a newly-connecting subscriber (the race
  between HTTP catch-up and WS registration) — #39 (M3.4).
- Multi-process / cross-process distribution (a second broadcast mechanism) —
  deferred by ADR-013.
- ADR-013 acceptance — #40 (M3.5).
