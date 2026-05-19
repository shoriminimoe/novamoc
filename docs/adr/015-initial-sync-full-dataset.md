# ADR-015: Initial Sync Transfers the Full Tenant Dataset

## Status

Accepted (2026-05-19)

## Context

When a user logs in on a new device or after clearing local storage, the client has no local data. To become functional — especially for later offline use — it must populate its local SQLite from the server.

Two broad models:

**Full initial sync.** Transfer the entire tenant dataset (schema plus current-state projections plus the event log from some starting point) to the client on first connect. Subsequent sync is incremental via the event log cursor.

**Partial / query-driven sync.** Transfer only the subset of data the client currently needs. Additional data is fetched as the user navigates. Offline availability is limited to what has been fetched.

Partial sync is a good fit for very large datasets or for per-user views of shared data, which is why engines like Zero emphasize it. Our context differs: tenant datasets are modest in size (small team, thousands to tens of thousands of records), every user in a tenant generally needs access to the whole dataset, and offline capability is a first-class requirement — a user in the field cannot fetch data on demand.

Full initial sync is appropriate when the full dataset fits comfortably on a client and every user needs all of it. We expect both conditions to hold.

## Decision

Initial sync transfers the full tenant dataset to the client. After initial sync completes, incremental sync proceeds via the event log cursor as described in ADR-011 and ADR-013.

**Flow.**
1. Client authenticates (once authentication is introduced) and identifies its tenant.
2. Client performs a schema fetch: all current `asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields` for its tenant. Client stores these locally and records the server's current `schema_version` as its `active_schema_version`.
3. Client performs a projection fetch: all entity projection tables (assets, maintenance records) and their field-value projection tables for its tenant. Data is transferred in batches — the server response is paginated to bound memory on both sides.
4. Server returns the current event log `seq` for the tenant as the client's initial cursor.
5. Client opens the WebSocket for live sync, using this cursor.

**Why transfer projections, not just events.** An alternative would be to send the client all events from seq 0 and have it fold locally. For the target dataset size this is wasteful — the event log is larger than the projection, and the fold work is duplicated on every new client. Sending the current projection (with HLCs intact so subsequent folds work correctly) is materially more efficient. The client is still fully event-sourced from that point forward: incoming events fold into the projection in the usual way.

**Batch shape.** Each batch is a set of rows from one or more projection tables plus a continuation token. The client requests successive batches until the server indicates completion. Batch size is tuned to balance network efficiency and memory; a starting target of a few thousand rows per batch is reasonable.

**Consistency.** The initial dataset returned must represent a consistent view — specifically, every projected field value's referenced field must exist in the returned schema, and the `seq` cursor returned must correspond to the state of the projection at the moment of transfer.

Because initial sync is paginated across multiple HTTP requests, holding one long-lived read transaction on the server is not a viable mechanism. Instead: each batch response includes the server's current `schema_version` and the current tenant `seq`. The client verifies that `schema_version` has not changed across batches. If it advances mid-transfer, the client discards partial state and restarts initial sync against the new version. Each batch itself is served under a single SQLite read snapshot (WAL), so an individual batch is internally consistent; cross-batch consistency is enforced by the `schema_version` invariant.

**Event log on the client.** After initial sync, the client's local event log begins empty (no events prior to the cursor are transferred — those are implicit in the projection). Going forward, every incoming event and every locally-generated event is appended to the client's event log as normal. The client's event log is therefore a forward-looking log starting at the initial-sync cursor; it is not a full historical copy of the server's event log. This is acceptable because the server remains the system of record for full history.

**Derived entity JSON.** The entity `properties` JSON projection (ADR-005, ADR-012) may be computed by the server during initial sync and transferred as-is, or computed on the client from the field-value projection after transfer. Computing on the client avoids transferring redundant data and is the default; computing on the server may be faster for very large datasets and is an optimization we can apply if needed.

**Failure and resumption.** If the initial sync is interrupted, the client resumes from the last completed batch using the continuation token. Partial initial state is acceptable as long as the client does not enter live-sync mode until initial sync completes — the client stays in an "initializing" state until all batches have arrived and local projections are fully built.

**Relation to normal sync.** Initial sync is a bulk projection transfer, distinct in shape from the incremental `/sync` endpoint. The incremental endpoint is only used after initial sync, when the client has a meaningful cursor.

## Consequences

Users get full offline capability from their first session onward: once initial sync completes, the entire tenant dataset is available locally regardless of connectivity.

Initial sync can be large for sizable tenants. For the target scale this is measured in megabytes, not gigabytes, and is acceptable. If tenant sizes grow beyond comfortable initial-sync scale, introducing partial sync would be a substantial change — a future ADR — but is not needed for the target use case.

A user who logs in on a new device incurs a one-time initial-sync cost. This is expected behavior and is surfaced in the UI as an "initializing" state with progress indication.

Initial sync's consistency requirement (schema matches projections matches cursor) interacts with schema changes during transfer. Reading in a single transaction on the server avoids this: the client sees a consistent snapshot at one schema version and enters live-sync at that version. If a schema change happens during initial sync, the client simply starts blocked on the newer version and must accept the upgrade before receiving further events — the same flow as any other schema change (ADR-009).

The client's local event log not being a full historical copy is a deliberate trade-off. Temporal queries far into the past must go to the server, which is acceptable — such queries are infrequent audit operations, not ordinary reads. The client's local event log is complete from the initial-sync point forward, which covers all events generated during the client's active use.
