# ADR-004: Use SQLite with Litestar for the Server

## Status

Proposed

## Context

The server needs a persistence layer and a web framework. It must serve HTTP endpoints for sync catch-up and schema fetch, hold long-lived WebSocket connections for real-time sync, validate incoming events against a current schema, and maintain an append-only event log per tenant.

Concurrency needs are modest. For a small-team multi-tenant deployment, aggregate write volume is bounded by humans entering maintenance data, not by machine-scale traffic. Read volume on the server is low compared to clients, which serve most reads from their local SQLite projections.

Candidate databases included Postgres, MySQL, and SQLite. Candidate frameworks included FastAPI, Starlette, and Litestar. The combination chosen is constrained by a preference for SQLite on the server (one storage model across client and server, simple deployment, no separate database process), and by the choice of Python for the server language.

## Decision

The server will be built on Litestar and will use SQLite as its persistence layer.

SQLite is configured with WAL mode enabled (`PRAGMA journal_mode=WAL`) and `PRAGMA synchronous=NORMAL` to balance durability with write throughput. Foreign keys are enabled (`PRAGMA foreign_keys=ON`). We use a single writer connection serialized by the application layer and a pool of reader connections; SQLite's concurrency model rewards this arrangement under WAL.

Litestar handles HTTP routing, WebSocket endpoints, dependency injection, and serialization. We use `msgspec` for event payload serialization where performance matters.

Tenant isolation is enforced at the application layer, with every synced-table row carrying a `tenant_id` column and every query scoped accordingly. We do not use a database-per-tenant model; all tenants share one SQLite database file. (See ADR-014 for the tenancy model.)

## Consequences

Deployment is simple: a single Python process with a single database file. Backups are file copies. Local development matches production closely.

SQLite imposes limits we accept. A single SQLite file on a single host caps horizontal scalability. For the target of small teams across a modest number of tenants, this is not a constraint in practice. If the deployment ever needs to scale beyond what a single SQLite file on a single host can serve, we would migrate to Postgres — an ADR at that point would record the decision.

The single-writer constraint means the sync endpoint serializes event appends. This is fine for our write volume but is worth remembering when reasoning about performance.

Running multiple server processes against a single SQLite file is possible with WAL but introduces coordination concerns for WebSocket fan-out (see ADR-013). We start with a single-process deployment and revisit if needed.

Choosing Litestar over FastAPI is a lower-stakes decision; either would work. Litestar's WebSocket primitives, dependency injection, and msgspec integration are well-suited to the sync endpoint shape we need, and the framework is actively developed.
