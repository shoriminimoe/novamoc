# ADR-001: Overall Architecture

## Status

Accepted

## Context

novaMOC is a local-first web application for tracking maintenance on user-defined asset types — vehicles, aircraft, equipment, or anything else a user chooses to model. It is the first ADR describing system shape; subsequent ADRs record specific decisions within the architecture laid out here.

The product has a few defining characteristics that drive the architecture:

**Local-first with offline support.** The application must remain fully functional without network connectivity for users who have previously logged in. "Offline" means "operating without network" rather than "operating on a device that has never synced." An initial online session is a prerequisite.

**User-defined schemas.** Users define the types of assets they track and the fields those assets carry. A user modeling a vehicle fleet defines fields like VIN, year, and mileage; a user tracking aircraft defines tail number, airframe hours, and last annual inspection date. The schema is data, not code. The same shape applies to maintenance record types.

**Homogeneous within a type.** All assets of a given type share the same fields. The schema is dynamic at the type level, not at the instance level.

**Small teams sharing a dataset.** Roughly 5-50 users per dataset, typically a workshop, fleet operations team, or maintenance crew. Multiple users may edit the same dataset, occasionally the same records, but true simultaneous edits to the same field are rare.

**Real-time collaboration when online.** When connected, users see each other's changes promptly, not on a polling interval.

**Multi-tenant.** A single server deployment hosts multiple independent datasets belonging to different teams or organizations, each fully isolated from the others.

## Decision

The system consists of three components: a browser client, a Python server, and a sync protocol connecting them.

**Client.** A browser-based single-page application backed by SQLite compiled to WebAssembly, persisted via OPFS (Origin Private File System). The client holds a full copy of its tenant's dataset locally and performs all reads and writes against the local database. User actions produce events that are applied optimistically to local projections and queued for propagation to the server.

**Server.** A Python service built on Litestar, backed by SQLite. The server is authoritative for the schema and acts as the sync hub for data: it validates incoming events, appends them to the canonical event log, and fans them out to other connected clients.

**Sync protocol.** An event-log-based protocol using Hybrid Logical Clocks (HLCs) for ordering and per-field last-write-wins (LWW) as the projection fold. Events flow bidirectionally between client and server. Data synchronization is peer-aware but server-mediated: clients never talk to each other directly. The server's authority is over *acceptance* — schema validation, HLC drift bound (ADR-006), and tenant scoping decide which events enter the canonical log. *Resolution* is not server-authoritative: the server applies the same deterministic fold (ADR-007) over the same accepted event set as every client, and arrives at the same projection.

**Event sourcing for data; current-state for schema.** All synchronized data is event-sourced: the event log is the source of truth, and entity tables are projections (ADR-002). Schema is not event-sourced — it is server-authoritative current state with a per-tenant monotonic version (the schema change log's `seq` for that tenant). Mutations are recorded in an append-only command-grain `schema_change_log` for audit; the schema projection tables hold current state directly and are not folded from the log.

**Two classes of data, handled differently.** Schema (asset types, their fields, maintenance record types, their fields) is server-authoritative and cannot be edited offline. Data (assets, maintenance records, field values) is bidirectionally synced and fully editable offline.

**Two transports for sync.** HTTP for initial sync, catch-up after offline periods, and as a fallback. WebSocket for real-time delivery while online. Both transports carry the same event protocol; the transport is interchangeable.

**Schema change model.** Schema changes require online connectivity. When the server's schema version advances, connected clients are notified and must explicitly accept the upgrade before sync resumes. This keeps the server free of per-version validation logic while giving users control over when their forms change under them.

**Tenant isolation.** Every row in every synced table is scoped to a tenant. The sync protocol scopes subscriptions, event logs, and queries to a single tenant throughout.

## Consequences

The client is a substantial piece of software, not a thin view over a server API. It holds data, generates HLCs, validates events against its cached schema, and manages a local pending-event queue. This is inherent to local-first and is the cost of the offline capability.

The server is comparatively simple. Its authoritative role is gatekeeping: validating events against a single current schema, enforcing the HLC drift bound, and scoping to a tenant before appending to the event log and fanning out. It does not compute merges, reconcile conflicts, or reason about history — the event log plus the LWW fold does that deterministically on every participant, server included.

SQLite on both sides gives us one mental model for storage and lets us share schema shape between client and server with minimal translation. It constrains our choice of off-the-shelf sync engines (most of which target Postgres on the server), which pushes us toward hand-rolling the sync layer. We consider this an acceptable trade for the simplicity and portability of SQLite.

The decision to require online connectivity for schema changes is a product-level constraint: users cannot restructure their data model in the field. In exchange, the sync layer avoids an entire class of offline-concurrent-schema-edit conflicts that are genuinely hard to resolve well.
