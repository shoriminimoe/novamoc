# ADR-003: Use SQLite Compiled to WebAssembly for Client-Side Storage

## Status

Proposed

## Context

The client needs durable local storage that survives reloads, supports rich queries across a full tenant dataset, and operates without network connectivity. The dataset includes assets, maintenance records, user-defined field values, a local event log, and a pending-event queue for events generated while offline. Typical reads include aggregate queries across assets and records: cost per asset per year, hours since last service, upcoming maintenance across a fleet, filters across multiple user-defined fields.

The candidate browser storage options are:

- **IndexedDB directly.** Ubiquitous, but its API is cursor-based and poorly suited to the aggregate and multi-field filtering queries this application needs. Joins, group-by, and ordered scans across secondary indexes are all possible in principle but painful in practice.
- **SQLite compiled to WebAssembly, backed by OPFS.** Provides full SQL including joins, aggregates, JSON functions, and indexes. Persisted via the Origin Private File System, which is designed for synchronous block-level access from WASM.
- **Higher-level local databases (RxDB, PouchDB, Dexie).** Each imposes its own data model and sync assumptions, many of which do not fit our user-defined-schema and event-sourced model well.

SQLite has an additional advantage for this project: we run SQLite on the server as well. One mental model for storage, near-identical schema DDL on both sides, and transferable query expertise.

## Decision

The client will use SQLite compiled to WebAssembly, persisted via OPFS, as its local storage engine.

We will use the official `@sqlite.org/sqlite-wasm` distribution with the OPFS VFS. All reads and writes from application code go through SQL. The local database contains the client's full tenant dataset — event log, projection tables, cached schema — plus local-only tables (the pending-event queue and the sync cursor).

We enable WAL mode and appropriate pragmas for durability and concurrency. We do not attempt to share a database connection across tabs; coordination, if needed, happens through OPFS locking semantics or a SharedWorker.

## Consequences

The client carries a non-trivial bundle size — SQLite-WASM is on the order of a megabyte — but this loads once and caches well. The runtime cost is negligible for the dataset sizes we anticipate.

OPFS with a SharedArrayBuffer-capable `FileSystemSyncAccessHandle` (required by `@sqlite.org/sqlite-wasm`'s OPFS VFS) has a narrower support envelope than OPFS in general. The supported baseline is:

- **Chrome / Edge:** version 109+ (January 2023 and later).
- **Safari:** version 17+ (September 2023 and later) on macOS and iOS.
- **Firefox:** `FileSystemSyncAccessHandle` shipped in Firefox 111, but the sqlite-wasm OPFS VFS is less battle-tested on Firefox than on Chromium; we treat Firefox as best-effort and retest on each sqlite-wasm release.

Cross-origin isolation headers (`Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp`) are required for SharedArrayBuffer in most browsers and must be set by the server serving the client bundle. The client performs a feature probe at startup and, if OPFS + sync-access-handle is unavailable, displays a blocking error message naming the supported browser versions rather than silently falling back to a non-persistent in-memory SQLite (which would quietly lose data on reload).

We gain full SQL on the client, which simplifies the rest of the system. User-defined field values queryable from projection JSON columns with `json_extract`, indexes on hot fields via generated columns, aggregates for reports, and efficient scans over the event log all become straightforward. Without this capability, large portions of the application would have to be implemented as manual cursor traversals.

The client-side schema DDL closely mirrors the server's, which makes cross-cutting changes easier to reason about and keeps the mental model singular.
