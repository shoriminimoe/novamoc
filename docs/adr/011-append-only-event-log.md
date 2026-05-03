# ADR-011: Append-Only Event Log as Sync Backbone

## Status

Accepted

## Context

The sync engine needs a way to represent state changes such that they can be:

- Generated offline without server coordination
- Ordered deterministically across participants (ADR-006 provides the ordering)
- Folded into a projection deterministically (ADR-007 provides the fold rule)
- Replayed idempotently (a client that retries a sync must not cause double-application)
- Streamed incrementally (a client with cursor N must efficiently receive events with sequence > N)
- Retained long enough to support offline clients returning after extended periods

A natural representation meeting these criteria is an append-only log of events, each carrying an HLC and enough structure to identify the target and the operation. This is the canonical event-sourcing pattern (ADR-002): the event log as the system of record, projections as derived views.

## Decision

The server maintains a single append-only `event_log` table. Every accepted event is appended to this log. The materialized current-state projections (ADR-005, ADR-012) are derived from the log under the fold defined in ADR-007.

**Schema (server).**
```sql
CREATE TABLE event_log (
  seq             INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id       TEXT NOT NULL,
  hlc             TEXT NOT NULL,
  schema_version  INTEGER NOT NULL,  -- schema seq at acceptance time (ADR-009)
  table_name      TEXT NOT NULL,     -- e.g. 'asset_field_values', 'assets'
  entity_id       TEXT NOT NULL,
  field_id        TEXT,              -- NULL for row-level operations
  op              TEXT NOT NULL,     -- 'set' | 'delete'
  value_json      TEXT,              -- NULL for deletes
  received_at     TEXT NOT NULL,
  UNIQUE (tenant_id, hlc)
);

CREATE INDEX idx_event_log_tenant_seq ON event_log(tenant_id, seq);
```

**Properties of the event log.**
- Append-only. Rows are never updated or deleted (except via explicit retention policies, which are out of scope here).
- Per-tenant sequencing via `(tenant_id, seq)`. Each tenant has its own monotonic view of the log even though the underlying `seq` is globally monotonic. Clients use their tenant's `seq` range.
- Idempotent by `UNIQUE (tenant_id, hlc)`. A retried event with the same HLC is recognized and skipped rather than double-applied.
- The HLC determines logical ordering and the LWW fold. `seq` determines streaming order for replication.

**Projection tables.** The current state of entities is held in projection tables (`assets`, `asset_field_values`, etc.) which are updated as events are applied:

```sql
INSERT INTO asset_field_values (tenant_id, asset_id, field_id, value_json, hlc)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (tenant_id, asset_id, field_id) DO UPDATE SET
  value_json = excluded.value_json,
  hlc        = excluded.hlc
WHERE excluded.hlc > asset_field_values.hlc;
```

The projection tables are derivable from the event log at any time. They are not redundant storage in the sense of duplicating information unnecessarily — they are a cache of the fold, maintained incrementally as each event is appended. The event log is the source of truth; the projection tables are disposable.

**Client-side mirror.** Clients maintain a local `event_log` table with the same shape plus an additional `pending_events` table for locally-generated events not yet acknowledged by the server. A successful sync moves events from `pending_events` into the acknowledged region of the local event log.

The client's local event log is **forward-looking from the initial-sync cursor** (ADR-015): it contains events the client has seen or generated since its initial sync completed, not a full historical copy of the server's log. Events prior to that cursor are implicit in the transferred projection. The server remains the system of record for full history; temporal queries reaching behind the client's cursor go to the server.

**Cursor-based replication.** Each client tracks `last_seen_seq` per tenant. Sync pulls events with `seq > last_seen_seq` ordered by `seq`. The server is stateless with respect to which events a given client has seen — the cursor lives on the client.

**Retention.** The event log is retained indefinitely for now. Offline clients returning after extended periods need to see the full history since their cursor, including tombstone events, to avoid resurrecting deleted data when they fold locally. A retention or compaction policy is explicitly out of scope for this ADR and would be addressed in a future ADR if needed.

## Consequences

The event log is the backbone of sync and the source of truth for all synchronized data. Every event acceptance, every client catch-up, and every fan-out is an operation on this log.

Clients and server share the same logical structure, which simplifies reasoning and testing. An event is the same shape on the wire, in the client event log, and in the server event log.

The log serves as an audit trail for free. "Who changed the mileage on truck 47 and when" is a query against `event_log`. This is a frequently desired feature in maintenance applications and falls out of the design without additional machinery.

Projection tables can be rebuilt from the log if they ever become inconsistent. This is a useful property for disaster recovery and for debugging: if a projection bug is found and fixed, existing data is re-derived by re-folding, not repaired row-by-row.

New projections can be added later without touching the write path. A reporting projection, a search index, or an analytics cube is a new consumer of the event log that folds events into whatever shape it needs. This decoupling is the central benefit of event sourcing and is available to us here by construction.

Indefinite retention implies bounded growth concerns at very long time horizons. For the target use case (small teams, modest write volume) this is not a practical concern for years of operation. A future ADR will address retention policies if and when they become necessary.

The `seq` column gives an efficient replication cursor. The `hlc` column gives the fold key. The two serve distinct purposes and are both present on every row; this is intentional and not a redundancy to eliminate.
