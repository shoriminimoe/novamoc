# ADR-014: Multi-Tenancy via Tenant-Scoped Rows in Shared Tables

## Status

Accepted

## Context

A single novaMOC server deployment hosts multiple independent datasets belonging to different teams or organizations. Each tenant has its own schema, its own assets, its own maintenance records, its own users (once authentication is introduced), and sees nothing from other tenants.

Candidate isolation models:

**Database-per-tenant.** Each tenant has its own SQLite file. Strongest isolation, simple backups per tenant, easy to detach a tenant. Costs: many more file handles, harder to administer at scale, more complex connection management, cross-tenant operations (none planned, but worth noting) become awkward.

**Schema-per-tenant (in Postgres).** Not available in SQLite.

**Tenant-scoped rows in shared tables.** One database file, every synced-table row carries a `tenant_id` column, every query scopes by tenant. Simplest operational model. Correctness depends on discipline: every query must include a tenant scope, or data leaks between tenants.

For a small-team product with modest per-tenant dataset sizes and modest tenant counts, row-level scoping is the pragmatic choice. Its correctness risks are addressable through discipline and testing.

## Decision

Multi-tenancy is implemented as tenant-scoped rows within shared tables. All synced data and all schema data are scoped by `tenant_id`.

**Tenant identification.** Each tenant has a stable `tenant_id` (ULID or UUID). The `tenant_id` is opaque and generated when the tenant is created.

**Data scoping.** Every row in every synced table (schema tables, entity projection tables, event log, field-value projection tables) carries a non-null `tenant_id` column. In projection tables (entity tables, field-value tables, schema tables), `tenant_id` is the leading column of the composite primary key. In the event log, the primary key is the globally-monotonic `seq`; tenant scoping is enforced by a `UNIQUE (tenant_id, hlc)` constraint for idempotency and by `idx_event_log_tenant_seq (tenant_id, seq)` for efficient per-tenant streaming (ADR-011). Every query scopes by `tenant_id` — there is no legitimate query that spans tenants.

**Event log scoping.** The event log is a single shared table with a `tenant_id` column. Cursors (`seq`) are effectively per-tenant from the client's perspective: a client's cursor progresses through events matching its tenant. The underlying `seq` is globally monotonic for implementation simplicity, but clients see only their tenant's subset (see ADR-011).

**Sync protocol scoping.** Every sync message — HTTP request or WebSocket — carries the tenant_id. The server validates that the client is acting on its own tenant at the point of auth (once auth exists). Until auth exists, the tenant_id is taken from the client's hello message; this is not secure and is acceptable only for the pre-auth development period.

**Fan-out scoping.** The server's subscriber registry (ADR-013) is keyed by tenant. Broadcasts for a committed event go only to subscribers of that event's tenant.

**Schema scoping.** Each tenant has its own schema. `asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields` all carry `tenant_id`. Schema versions are per-tenant: tenant A's schema version advancing has no effect on tenant B's clients.

**Client scope.** A client is associated with exactly one tenant at a time. Its local SQLite holds only that tenant's data. Switching tenants (if ever supported) requires a new client context with a fresh local database — clients do not multiplex tenants.

**Indexing.** Indexes on synced tables include `tenant_id` as a leading column where appropriate, so per-tenant queries do not scan across tenants.

## Consequences

Operational model is simple: one database file, one process, one backup. Deployment and development are uncomplicated.

Correctness depends on disciplined query construction. Every query must scope by tenant. We mitigate this through:

- A repository or query-builder layer that takes `tenant_id` as a required parameter and refuses to construct unscoped queries
- Tests that exercise cross-tenant isolation explicitly
- Code review attention to any query that does not visibly scope by tenant

Without authentication (ADR-001 defers auth), tenant isolation is advisory: a malicious client could claim any tenant_id. This is acceptable for initial development but must be revisited alongside authentication. A follow-up ADR will address authenticated tenant membership.

The event log's globally-monotonic `seq` works correctly per-tenant because clients filter by their tenant; the `seq` values a given client sees are sparse but monotonic within their tenant. This is simpler to implement than per-tenant sequence counters and produces the same observable behavior.

Scaling characteristics: a single SQLite file with modestly-sized tenants and modestly-many tenants is well within SQLite's comfortable operating range. Should the product grow beyond what a shared-file multi-tenant SQLite can serve, options include per-tenant database files or migration to Postgres; each would be its own ADR at that time.
