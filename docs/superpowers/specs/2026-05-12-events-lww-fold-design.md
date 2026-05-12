# Design: per-field LWW fold for `POST /events`

## Status

Approved 2026-05-12. Implemented in PR #67 (M1.6).

## Problem

M1.5 (PR #66) made the events endpoint durable: each accepted event is
appended to `event_log` inside a per-event savepoint. But the entity
projection that clients read (the `*_field_values` EAV table, and
later the entity-table column / properties JSON cell) is still empty —
every accepted event survives in the log and not yet anywhere a query
can see it.

M1.6 closes the first half of that gap. After the `event_log` insert,
each accepted `Created` / `Updated` event's `values` payload must be
folded into the per-field projection (`asset_field_values` /
`maintenance_record_field_values`) under the LWW rule from ADR-007:
the highest-HLC event wins, ties don't apply, late arrivals lose
silently.

The fold has three hard constraints that drive the design:

1. **Atomicity with the log.** The two projections (log + EAV) must
   stay consistent. If the fold fails after the log insert, the log
   row must roll back too, or a replay would re-fold the same values
   and corrupt the EAV.
2. **HLC-strict-greater, in SQL.** Catch-up sync delivers events out
   of order. A stale event seen after a newer one must not overwrite —
   and the check must live in the DB (a read-modify-write in Python
   would race with concurrent batches).
3. **Idempotency at the projection grain.** Re-delivery of the same
   HLC (already handled at the log grain by `UNIQUE(tenant_id, hlc)`)
   must also not change the projection. The strict-greater
   guard handles this for free: equal-HLC re-arrival fails the
   `WHERE` and the row is untouched.

A side effect of building the fold is that the M1.7 entity-table
projection update (the `properties` JSON / `col:*` columns) needs an
applied/skipped signal to decide whether to write — if the EAV upsert
was skipped (a higher-HLC value already won), the entity-table cell
must not be touched either, or the two projections diverge. M1.6 must
surface that signal even though M1.7 is what consumes it.

## Goals

1. Append-then-fold for every accepted `Created` / `Updated` event,
   inside one savepoint, so the log and EAV projection are always in
   the same state.
2. Pure-SQL HLC guard via `INSERT ... ON CONFLICT ... DO UPDATE WHERE
   excluded.hlc > <table>.hlc RETURNING hlc`. No read-modify-write in
   application code.
3. One conditional upsert per `(entity, field)` cell. A batch with
   N events × M fields each is N×M round-trips — measured against
   correctness, not throughput, this is the right grain (and SQLite
   wire-protocol-free, so the cost is real but negligible at this
   scale).
4. Return the applied/skipped bool so M1.7 can gate the entity-table
   projection on it.
5. Land as a single commit on top of M1.5 (PR #66). No wire-format
   change, no behaviour change visible to the client other than that
   the EAV now actually fills up.

## Non-goals

- **Entity-table projection.** The `properties` JSON / `col:*` column
  updates land in M1.7. M1.6 writes only the per-field EAV.
- **Row-state events.** `Deactivated` / `Activated` carry no per-field
  payload and so the fold is a no-op for them. The row-state
  projection (tombstone bit, restore) lives in M1.8.
- **Cross-cell HLC ordering.** Each `(entity, field)` cell has its
  own HLC and is LWW-independent of every other cell — that's the
  ADR-007 design, and the per-field upsert preserves it. No batching
  / coalescing across cells.
- **Validation.** Unknown-field / value-type-mismatch checks already
  run in the M1.4 handler dispatch upstream of `append_event`. The
  fold trusts that whatever reaches it is shape-correct.
- **Schema for the fold.** `col:*` keys (reserved-column writes) and
  UUID-string keys (user-defined fields) both land in
  `*_field_values.field_id` as opaque strings. The fold is generic
  over the key shape; M1.7's entity-table writer is what distinguishes
  them.

## Architecture

### Module layout

```
src/py/novamoc/domain/events/
├── _fold.py          # NEW: apply_field_value(session, FieldUpsert) -> bool
├── _bundle.py        # MODIFIED: append_event now appends AND folds in one savepoint
├── _handlers/        # unchanged: still call services.append_event(event)
└── controllers/_events.py  # unchanged
```

### `_fold.py` — the SQL primitive

`apply_field_value(session, upsert: FieldUpsert) -> bool` is the
single entry point. It owns the SQL and nothing else — no transaction,
no per-event orchestration, no validation. Callers wrap it in their
own savepoint.

`FieldUpsert` is a frozen dataclass bundling the addressing tuple +
value + HLC:

```python
@dataclass(frozen=True, slots=True)
class FieldUpsert:
    family: EntityFamily
    instance_id: UUID
    field_id: str
    value: Any
    hlc: str
```

The bundle is deliberate — it keeps `apply_field_value`'s signature at
two parameters so callers can't accidentally transpose `value` and
`hlc` (both `str` at the call site for col-keyed fields) or
`instance_id` and `field_id`.

Family routing lives in one private table-of-truth:

```python
_PROJECTION = {
    EntityFamily.ASSET:              (AssetFieldValue, "asset_id"),
    EntityFamily.MAINTENANCE_RECORD: (MaintenanceRecordFieldValue, "maintenance_record_id"),
}
```

The same fold runs for both families; only the destination table and
the instance-column name change. A third family later is one row.

The SQL itself, via `sqlalchemy.dialects.sqlite.insert`:

```python
INSERT INTO <table> (tenant_id, <instance_col>, field_id, value_json, hlc)
VALUES (...)
ON CONFLICT (tenant_id, <instance_col>, field_id) DO UPDATE
  SET value_json = excluded.value_json,
      hlc        = excluded.hlc
  WHERE excluded.hlc > <table>.hlc
RETURNING hlc;
```

The `RETURNING` clause yields a row iff the `INSERT` actually
inserted (no conflict) or the `DO UPDATE` actually ran (the `WHERE`
clause passed). A skipped `DO UPDATE` produces no row. So
`result.first() is not None` is the applied/skipped bool the function
returns.

`tenant_id` is read from `current_tenant_id.get()` (the contextvar
the tenant-scoping listeners use). A `None` is a wiring bug — the
middleware should have populated it upstream — and raises a
`RuntimeError` rather than letting the row silently lack a tenant.

### `_bundle.py` — append + fold in one savepoint

`EventServiceBundle.append_event(event)` (introduced in M1.5) gains a
second responsibility: after the `event_log` insert, walk the body's
field values and call `apply_field_value` for each, all inside the
same `begin_nested()` block:

```python
async def append_event(self, event: EventEnvelope) -> EventOutcome:
    session = self.event_log_service.repository.session
    try:
        async with session.begin_nested():
            await self.event_log_service.create(data={...}, auto_commit=False)
            for field_id, value in _values_for_fold(event.body).items():
                await apply_field_value(
                    session,
                    FieldUpsert(
                        family=event.family,
                        instance_id=event.instance_id,
                        field_id=field_id,
                        value=value,
                        hlc=event.hlc,
                    ),
                )
    except RepositoryIntegrityError:
        return EventOutcome(hlc=event.hlc, outcome="duplicate")
    return EventOutcome(hlc=event.hlc, outcome="accepted")
```

A small `_values_for_fold(body)` helper returns `body.values` for
`Created` / `Updated` and `{}` for `Deactivated` / `Activated`. The
loop is therefore a no-op for row-state events without a branch at
the call site.

`apply_field_value`'s return value is **discarded** in M1.6. The
applied/skipped signal is the M1.7 hook — the API surfaces it, but no
caller reads it yet. (Per CLAUDE.md's "no half-finished implementations"
rule, we don't add a placeholder `_applied = ...; del _applied` line;
when M1.7 needs the signal, M1.7 captures it.)

### Why the fold lives in the bundle (not the handler)

The atomicity constraint forces this. The savepoint that protects the
`event_log` insert against `UNIQUE(tenant_id, hlc)` collisions is
opened inside `append_event`. If the fold ran in the handler *after*
`append_event` returned, it would land outside the savepoint and a
fold failure would leave the log row committed without the projection
update — the exact failure mode the spec rules out.

Two alternatives were considered and rejected:

- **Open the savepoint in the handler.** The handler would
  `async with session.begin_nested()` itself and call
  `append_event` inside it. This works but inverts the bundle's
  current contract (the bundle owns transaction boundaries) and
  duplicates the `RepositoryIntegrityError → duplicate` path in every
  handler.
- **Return the field list from `append_event` for the handler to
  fold.** This pushes the savepoint discipline onto callers — a
  future row-state handler that forgets to wrap its fold in a
  savepoint silently corrupts state. The current shape makes
  atomicity an unbreakable invariant of `append_event`.

The cost is a small split-responsibility: `append_event` now does both
the log insert and the field-value upserts. The boundary is documented
in its docstring; M1.7 will add a third responsibility (entity-table
upsert), and a future refactor can split if the function ever grows
unwieldy.

### `db/_listeners.py` — incidental fix

The fold is the first code path that drives a Core-level
`insert(table).values(tenant_id=...)` (the ORM `session.add` path
M1.5 used hit Layer 2, not Layer 3). That exposed a latent bug in
Layer 3's `_values_carries_tenant`: it was checking
`Column.name == "tenant_id"` on `_values` keys, but SQLAlchemy 2.x
normalises `.values(tenant_id=...)` to a **string-keyed** dict. The
prior code returned `False`, Layer 3 raised
`UnscopedQueryError("Tenant-scoped INSERT lacks tenant_id...")`, and
every fold failed.

Fix is a one-liner: a `_is_tenant_key(key)` helper that accepts both
the string and the Column-object key shape. The docstring is updated
to enumerate both. Layer 3's other shape branches (`_multi_values`,
explicit `params` dict) were already string-keyed and unaffected.

This fix is in scope for M1.6 because nothing before M1.6 exercised
the broken path. Splitting it into a separate PR would land a fix for
a bug that never manifests on its own.

## Tests

### New: `tests/events/test_fold.py`

Six unit tests, all directly against `apply_field_value` with a real
SQLite session (no mocks). Mirrors the cells of the LWW truth table:

* `test_forward_order_stores_latest_value` — two upserts in HLC order;
  both applied; final state is the later value.
* `test_reverse_order_keeps_higher_hlc` — two upserts in reverse
  order; second one returns `applied=False`; row unchanged.
* `test_equal_hlc_does_not_apply` — strict-greater means equal HLC
  loses. This is what makes the projection idempotent under
  re-delivery (the log layer's `UNIQUE(tenant_id, hlc)` already
  rejects re-delivery, but tests exercise the projection-level
  guarantee independently).
* `test_null_value_is_recorded` — `None` is the clear-cell sentinel;
  the fold writes it like any other value (no special branch).
* `test_maintenance_record_family_routes_to_correct_table` — proves
  the `_PROJECTION` family→table table works in both directions: the
  maintenance-record write lands in `maintenance_record_field_values`
  and **does not** appear in `asset_field_values`.
* `test_different_fields_on_same_entity_are_independent` — two
  fields on one entity, written out of HLC order; both apply because
  the LWW comparison is per `(entity, field)`, not per entity.

These tests do not go through `append_event` — they exercise the SQL
primitive directly. End-to-end coverage (POST /events → log + EAV
both populated) comes via the existing endpoint tests, which already
hit `append_event` and continue to pass without modification.

### What stays unchanged

- `tests/events/test_bundle.py` — `append_event` accepted/duplicate
  contract is unchanged at the wire level.
- `tests/events/test_endpoint_*.py` — all 12+ endpoint tests still
  pass; the fold runs but no assertion was looking at
  `*_field_values` rows.
- `tests/events/test_handlers_*.py` — handlers still call
  `services.append_event(event)`; the test contract is unaffected.

End-to-end assertions on the projection content land with the M1.9
endpoint E2E suite (issue #28).

## Out of scope (defer to M1.7+)

- **Entity-table projection (M1.7, issue #26).** Update
  `<entity>.properties` JSON / `col:*` columns from the same event,
  gated on `apply_field_value`'s returned bool. The bool exists today
  exactly because M1.7 needs it.
- **Row-state events (M1.8, issue #27).** Tombstone bit on
  `Deactivated`, restore on `Activated`, both with their own LWW
  guard against the entity-level HLC. The fold loop is already a
  no-op for these bodies — M1.8 adds the row-state writer alongside.
- **End-to-end projection assertions (M1.9, issue #28).** Tests that
  POST `/events` and then read `*_field_values` to confirm the fold
  landed correctly through the full controller stack.
- **Catch-up replay (M2.4, issue #34).** `GET /events?since=<seq>`
  re-emits events; on the client side, the same fold logic (running
  against the WASM SQLite db) consumes them with the same HLC guard.
  Server-side, the same `apply_field_value` runs when a fan-out event
  arrives via WebSocket (M3).
- **Bulk fold for initial sync (M2.3, issue #33).** `GET /sync/initial`
  returns the projection directly; the fold runs against the event
  stream at first hydration. Same `apply_field_value` reused.

## Migration

- PR #67 lands as one commit on top of M1.5 (PR #66, now merged to
  main). No schema change, no migration. The `*_field_values` tables
  already exist (M0); M1.6 starts filling them.
- CLAUDE.md's "Events endpoint (`POST /events`)" section is updated
  in a follow-up commit (M1.7 / M1.8 timeframe) to describe the fold
  as part of the per-event pipeline. The interim README for the bundle
  (`_bundle.py` docstring) covers what M1.6 needs.
- No new ADR. The fold is the implementation of ADR-007 (HLC LWW) +
  ADR-012 (EAV projection); it doesn't decide anything new.
