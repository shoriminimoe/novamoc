# ADR-012: EAV-Grain Events with Materialized JSON Projections

## Status

Proposed

## Context

ADR-005 establishes that reads operate over entities with a `properties` JSON column — one row per entity, user-defined values accessed via `json_extract`. ADR-007 establishes per-field last-write-wins as the projection fold, which forces the event log to record events at field grain: the fold can only resolve `(entity, field)` writes independently if it sees writes at that grain. Events never target `properties` directly; the JSON column is purely a read projection, never an event target.

So events are field-grain by construction, and reads are entity-grain JSON by construction. What ADR-005 and ADR-007 do not specify is how the two are connected: what the fold actually runs against (the `properties` JSON column has no per-field HLC metadata to drive an HLC-guarded LWW), and how the JSON column stays consistent with the fold result. That is the gap this ADR fills.

The resolution introduces a second projection. Field-grain events fold into per-field projection tables that carry the HLC metadata the fold needs. The entity-grain `properties` JSON is a downstream projection of those tables, updated as a side effect of each field-value upsert. A disciplined write path keeps both consistent.

## Decision

All non-schema data that is synchronized produces events at field grain. Each event targets a single (entity, field) pair — or an entire row for create and delete operations. Entity tables expose a per-entity JSON projection (ADR-005) for reads. Whenever an event updates a field, the corresponding entity's JSON properties are updated in the same transaction to reflect the new value.

**Field-grain projection tables.** For each entity family that carries user-defined fields, a per-field-value table holds the current folded value of each field of each entity:

```sql
CREATE TABLE asset_field_values (
  tenant_id   TEXT NOT NULL,
  asset_id    TEXT NOT NULL,
  field_id    TEXT NOT NULL,
  value_json  TEXT,               -- NULL means the field was cleared
  hlc         TEXT NOT NULL,
  node_id     TEXT NOT NULL,
  PRIMARY KEY (tenant_id, asset_id, field_id)
);

CREATE TABLE maintenance_record_field_values (
  tenant_id             TEXT NOT NULL,
  maintenance_record_id TEXT NOT NULL,
  field_id              TEXT NOT NULL,
  value_json            TEXT,
  hlc                   TEXT NOT NULL,
  node_id               TEXT NOT NULL,
  PRIMARY KEY (tenant_id, maintenance_record_id, field_id)
);
```

Parallel tables exist on client and server. The fold is applied per row, which because of the primary key structure means per `(entity, field)` — the grain we need. These tables are projections of the event log (ADR-011), maintained incrementally as events are applied.

**Fixed (non-user-defined) entity columns** are event-sourced at column grain. Each event records the table, entity_id, and column name in `field_id` using a reserved `col:` namespace (e.g. `col:name`). Each fixed column folds under LWW independently, the same way user-defined fields do.

The `col:` prefix exists because the event log's single `field_id` column carries two naming spaces — opaque user-field ids allocated by the meta-schema, and human-readable fixed-column names like `name` or `type_id`. The prefix serves three purposes:

1. *Routing at apply time.* A fixed-column event lands in `assets.<column>`; a user-field event lands in `asset_field_values`. The prefix is the routing signal, so the apply path does not need a meta-schema lookup per event to decide where the value goes.
2. *Structural disjointness.* Without a prefix, the two namespaces would only be disjoint by convention on the id allocator. The prefix makes the disjointness a property of the encoding, not a hidden invariant that can be violated silently.
3. *Audit readability.* `col:name` in `event_log` is unambiguous; a bareword `name` would not be distinguishable from an opaque user-field id without consulting the meta-schema.

**Row creation and deletion.** Row creation is an event with `field_id = NULL` and `op = 'set'` carrying **no column values** — it asserts only that the entity exists under its id. Columns are set by separate per-column events. This keeps creation and column-set disjoint so there is no ambiguity about which fold wins when a row-create's "payload" collides with a later column set. In practice, creating an asset with initial values is a batch of events in one transaction: one existence event followed by one event per column and per user-defined field.

Row deletion is an event with `field_id = NULL` and `op = 'delete'`. Row visibility is governed solely by the highest-HLC row-level event for the entity: the row is visible iff that event is `op = 'set'`. Field-grain events apply to `*_field_values` regardless of the row's current visibility — a post-delete field set updates the field-value projection but does not unhide the row. A subsequent row-level `set` event with HLC greater than the latest delete (a "restore") brings the row back; on restoration, `properties` reflects the latest LWW result for every field, including any post-delete field events. There is no separate `restore` op — restoration is a row-level `set`, the same shape as creation, distinguished only by what came before it.

This rule makes deletes sticky. A field edit on a deleted row does not silently resurrect it with stale pre-delete values; resurrection requires an explicit row-level event. Field events that land on a deleted row are not lost — they update `*_field_values` so that a future restore surfaces the latest fold for every field — but they remain invisible until a restore event flips row state.

The entity table carries two derived columns to materialize this state:

```sql
ALTER TABLE assets ADD COLUMN deleted       BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE assets ADD COLUMN row_state_hlc TEXT    NOT NULL;
```

`row_state_hlc` is the HLC of the most recent row-level event applied to this entity; `deleted` is the resolved state derived from that event's op. When a row-level event arrives:

```sql
UPDATE assets
   SET deleted       = (excluded.op = 'delete'),
       row_state_hlc = excluded.hlc
 WHERE id = ? AND tenant_id = ?
   AND excluded.hlc > row_state_hlc;
```

Both columns are HLC-guarded so a late-arriving stale row-level event leaves the state untouched. Reads filter on `WHERE deleted = 0`. Like `properties`, both columns are projection state — they can be rebuilt at any time by folding row-level events for the entity under LWW.

**Entity-grain JSON projection.** Entity tables retain a `properties` JSON column as in ADR-005. Whenever a row in a `*_field_values` table is updated on the client or server, the `properties` JSON of the corresponding entity row is updated to reflect the new value. The mechanism is an application-level transaction: append the event to the event log, attempt the HLC-guarded upsert into the field-value projection, and — **only if that upsert actually updated the row** — write the new value into the entity's JSON column. All three writes happen in one transaction.

This conditional write is essential. The field-value upsert in ADR-011 is guarded by `WHERE excluded.hlc > asset_field_values.hlc`, so a late-arriving stale event leaves the field-value projection untouched. If the JSON update were unconditional, a stale event would still overwrite the JSON key, and the two projections would diverge. The concrete pattern:

```
1. INSERT INTO event_log ...
2. INSERT INTO asset_field_values ... ON CONFLICT ... DO UPDATE ...
   WHERE excluded.hlc > asset_field_values.hlc
   RETURNING 1;
3. If step 2 returned a row (the upsert actually applied):
     UPDATE assets SET properties = json_set(properties, '$.<field>', <value>)
     WHERE id = ? AND tenant_id = ?;
```

Equivalent behavior can be implemented as a SQLite trigger if both environments (client and server) support triggers cleanly; the semantics are the same. Starting with application-level transactions gives more explicit control and easier debugging; migrating to triggers later is an implementation detail.

**Clears.** Setting a field value to NULL via a `set` event with `value_json = NULL`, or a `delete` event, removes the corresponding key from the JSON properties projection.

**Event log entries.** Data events are recorded in the event log (ADR-011) at field grain. One event per field write. This is the grain at which events flow over the wire and the grain at which the fold resolves them.

**Reads.** Application queries read from entity tables and use `json_extract(properties, '$.field_name')` for user-defined fields, as in ADR-005. The field-value tables are projection bookkeeping; they are not the primary read surface for application code.

## Consequences

We get per-field fold semantics without sacrificing the JSON read projection. Two mechanics editing different fields on the same truck both have their events contribute to the projection. Two mechanics editing the same field fold by HLC with no data loss in the event log — only in the projection value.

There is a derived relationship between the field-value tables and the JSON properties:

- The event log (ADR-011) is the source of truth.
- The field-value tables are a projection of the event log at field grain, carrying HLC metadata for incremental fold.
- The JSON properties are a projection optimized for application reads and query patterns.
- Keeping all three consistent requires a disciplined write path — every event append updates the field-value projection and the JSON projection in one transaction.

Storage cost is higher than a projection-only model: each field value exists in the event log, as a row in the field-value projection, and as a JSON key in the entity projection. For the target scale (small teams, thousands-to-tens-of-thousands of assets with tens of fields each) this is negligible.

The write path is slightly more complex: a field edit is three related table writes (event log, field-value projection, JSON projection), not one. This complexity is encapsulated in the sync engine and does not leak into application code. Application code issues a single command; the engine handles the event append and the projection updates.

Reads remain fast and natural. Queries like "assets of type X where mileage > N" use `json_extract` on the entity's `properties`, optionally backed by a generated-column index. No joins into the field-value tables are needed for reads. Reads add a `WHERE deleted = 0` predicate to filter out tombstoned rows.

Deletes are sticky and restorable. A deleted row stays deleted until an explicit row-level `set` event with a higher HLC restores it. Field events arriving while a row is deleted are still applied to `*_field_values`, so a future restoration brings back the latest LWW result for every field — including any post-delete edits — without losing data. This matches the soft-delete pattern users already know (delete makes it disappear; restore brings it back) and avoids the failure mode where a single post-delete field edit silently resurrects an entity with stale pre-delete values for every other field.

If a query ever needs field-level history — "what was the mileage on truck 47 six months ago" — it goes to the event log directly. This is a temporal projection and is acceptable to be slower than ordinary entity reads, consistent with the event-sourcing discipline that reserves the log for audit and temporal queries.
