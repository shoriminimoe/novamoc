# ADR-012: EAV-Grain Events with Materialized JSON Projections

## Status

Proposed

## Context

ADR-005 establishes that reads operate over entities with a `properties` JSON column — one row per entity, user-defined values accessed via `json_extract`. ADR-007 establishes per-field last-write-wins as the projection fold, which forces events to be recorded at field grain. Events never target `properties` directly; the JSON column is purely a read projection.

This ADR fills the operational gap between those two decisions: what the per-field fold actually runs against (since `properties` has no per-field HLC metadata), and how the JSON column stays consistent with that fold.

## Decision

**Field-grain projection tables.** Each entity family with user-defined fields has a per-field-value table holding the current folded value of each `(entity, field)`:

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

The fold is per-row, which under the primary key is per `(entity, field)` — the grain ADR-007 needs. These tables are projections of the event log (ADR-011), maintained incrementally on both client and server.

**Fixed (non-user-defined) entity columns** are event-sourced at column grain. The event records the column name in `field_id` under a reserved `col:` namespace (e.g. `col:name`); each fixed column folds under LWW independently. The prefix routes events at apply time without a meta-schema lookup, makes the user-field-id and column-name namespaces structurally disjoint rather than disjoint-by-convention, and keeps log rows unambiguous in audit contexts.

**Row creation.** A row-level event with `field_id = NULL` and `op = 'set'` carries no column values — it asserts only that the entity exists. Columns are set by separate per-column events, so creation and column-set never compete in the fold. Creating an asset with initial values is a batch in one transaction: one existence event plus one event per column and per user-defined field.

**Row deletion and visibility.** A row-level event with `field_id = NULL` and `op = 'delete'` tombstones the entity. Row visibility is governed solely by the highest-HLC row-level event for the entity: the row is visible iff that event is `op = 'set'`. Field-grain events apply to `*_field_values` regardless of visibility — post-delete edits update the projection but do not unhide the row. A later row-level `set` with HLC greater than the latest delete restores the row, at which point `properties` reflects the latest LWW for every field, including any post-delete edits. There is no separate `restore` op; restoration is just a row-level `set`.

The entity table carries two derived columns to materialize this state:

```sql
ALTER TABLE assets ADD COLUMN deleted       BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE assets ADD COLUMN row_state_hlc TEXT    NOT NULL;
```

`row_state_hlc` is the HLC of the most recent row-level event; `deleted` is its resolved state. Apply rule:

```sql
UPDATE assets
   SET deleted       = (excluded.op = 'delete'),
       row_state_hlc = excluded.hlc
 WHERE id = ? AND tenant_id = ?
   AND excluded.hlc > row_state_hlc;
```

Reads filter on `WHERE deleted = 0`. Like `properties`, both columns can be rebuilt by re-folding row-level events from the event log.

**Entity-grain JSON projection.** The `properties` JSON column is a downstream projection of `*_field_values`. Whenever a field-value row is updated, the corresponding JSON key is updated in the same transaction. The JSON write must be conditional on the field-value upsert actually applying; otherwise a stale event would update the JSON without updating the field-value table, diverging the two projections:

```
1. INSERT INTO event_log ...
2. INSERT INTO asset_field_values ... ON CONFLICT ... DO UPDATE ...
   WHERE excluded.hlc > asset_field_values.hlc
   RETURNING 1;
3. If step 2 returned a row:
     UPDATE assets SET properties = json_set(properties, '$.<field>', <value>)
     WHERE id = ? AND tenant_id = ?;
```

Equivalent behavior can be implemented as a SQLite trigger if both environments support triggers cleanly; the semantics are the same. Application-level transactions give more explicit control to start with.

**Clears.** A `set` event with `value_json = NULL`, or a field-grain `delete`, removes the corresponding key from `properties`.

**Reads.** Application queries read from entity tables using `json_extract(properties, '$.field_name')` for user-defined fields, as in ADR-005. The `*_field_values` tables are projection bookkeeping, not a read surface for application code.

## Consequences

Two mechanics editing different fields on the same truck both contribute to the projection. Two mechanics editing the same field fold by HLC; no event is lost in the log, only in the projection value.

Storage and write-path cost are real but bounded: each field value exists in the event log, the field-value projection, and the JSON projection, and a field edit is three coordinated writes. For small teams with thousands of assets this is negligible, and the complexity is encapsulated in the sync engine.

Reads stay fast and natural. `json_extract` over `properties` (optionally indexed via a generated column) handles user-defined fields without joining into `*_field_values`. The added `WHERE deleted = 0` filter is cheap and standard.

Deletes are sticky and restorable. A post-delete field edit cannot silently resurrect an entity with stale values for every other field — restoration requires an explicit row-level event, and no field event is lost while waiting for one.

Field-level history — "what was the mileage on truck 47 six months ago" — goes to the event log directly. This is a temporal projection, acceptably slower than ordinary entity reads and consistent with the event-sourcing discipline that reserves the log for audit and temporal queries.
