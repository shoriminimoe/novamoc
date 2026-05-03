# ADR-008: Server-Authoritative Schema

## Status

Accepted

## Context

The user-defined schema (asset types, their fields, maintenance record types, their fields) could in principle be edited from any client at any time and propagated as events like any other data. This was our initial direction, but it introduces a large class of offline conflict cases that are genuinely hard to resolve well: two clients concurrently adding fields with the same name, one client renaming while another generates events against the field, concurrent type changes on a field with existing values, concurrent removal and use.

These conflicts are qualitatively different from data conflicts. A per-field LWW fold of "rename field X to Y" against "delete field X" produces a clearly wrong outcome no matter which wins. There is no natural CRDT for schema evolution that preserves user intent across arbitrary concurrent edits.

The alternative: make the schema server-authoritative. Clients read the schema but cannot modify it offline. Schema edits go through the server while online. This eliminates concurrent schema edits by construction.

This constrains the product. Users in the field cannot restructure their data model offline. In practice this is acceptable: schema edits are rare, deliberate, and typically performed at a desk. Day-to-day work (recording maintenance, inspecting assets, logging parts) uses the schema as it exists and is fully offline-capable.

The schema is the one part of the system that is deliberately not event-sourced (ADR-002). It is current-state with a monotonic version number. The trade-off is deliberate: event sourcing's strengths (offline writes, deterministic merge, audit) are strongest for data and weakest for schema evolution.

## Decision

The server is the sole authority for the schema. Schema state lives in the meta-schema tables introduced in ADR-005 (`asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields`); these tables hold *current* state directly. Mutations are issued by clients as commands and recorded server-side in an append-only `schema_change_log` for audit and upgrade-diff purposes. The change log is not folded into the projection; it is a record of what happened, not the source of the projection's state.

**Command-vs-event split.** Any client may POST a schema-change command to `/schema` while online. The server validates the command against the current projection, applies the corresponding mutation, and appends one row to `schema_change_log`, all in a single transaction. The requesting client does not reflect the change locally until the corresponding broadcast arrives over the normal post-commit notification path; the round-trip is the acknowledgement. There is no local optimistic write for schema and no pending-schema queue. Offline clients cannot edit schema (ADR-001).

**Lifecycle on schema entities.** Both type rows and field rows carry an `active: BOOLEAN` column. A row is *active* when `active = true` and *tombstoned* when `active = false`. The entity `id` is stable across the lifecycle. `UNIQUE(tenant_id, name)` on type tables and `UNIQUE(tenant_id, parent_id, name)` on field tables apply across both states — a name is reserved by an entity for the entity's lifetime. Bringing a tombstoned entity back is `activate_*` against its existing `entity_id`, not a fresh `create_*` reusing the name.

**Six command verbs per entity.** Commands are named `<verb>_<entity_kind>` in a single flat enum (`create_asset_type`, `clear_maintenance_record_type_field`, etc.). Each verb is one orthogonal intent:

| Verb | Effect | Payload | Confirmation |
|---|---|---|---|
| `create_*` | new row inserted at the requested `entity_id`; PK or name collision → 409 `name_reserved` | full definition; required fields enforced at the decoder | standard |
| `activate_*` | flips `active = true`; missing → 404, deactivated → activated, already active → no-op | absent or `{}` | standard |
| `update_*` | properties modified (including renames); allowed regardless of `active` state; UNIQUE on rename catches collisions | only the changed properties | standard |
| `deactivate_*` | flips `active = false`; data values preserved; the JSON key stays in `properties` on each entity row | absent or `{}` | standard |
| `clear_*_field` | wipes `*_field_values` rows and strips the field's key from each affected `properties` JSON; idempotent; fields only | absent or `{}` | "are you sure?" |
| `delete_*` | hard-deletes the row; cascades dependent rows (type-level → fields and entities); frees the name | absent or `{}` | type-the-name |

`deactivate_*` is the routine "remove from the UI" path — data preserved, name reserved, recoverable via `activate_*`. `delete_*` is admin-tier and terminal. UI visibility for deactivated rows is a read-time concern (`WHERE active = true`).

**Reads.** Clients fetch the current schema projections from the server (filtering on `active = true` or carrying the flag through per the use case) and cache them locally. The cached projections are available offline for data-event generation, validation, and rendering forms.

**`schema_change_log` shape.** One row per accepted command. Columns: `tenant_id`, `seq` (BigInt — composite PK with `tenant_id`, dense per-tenant `1, 2, 3, …` computed at insert time as `MAX(seq) + 1` within the tenant), `command` (TEXT — see *Command vocabulary at the storage boundary* below), `entity_id` (UUID — the type or field the command targets), `payload` (JSON, structured per command), `committed_at`, and `actor_id` (NULL until auth lands). The composite PK's leading column is `tenant_id`, so its implicit index serves per-tenant streaming for upgrade diffs without a separate index. There is no application-level idempotency key: the `POST /schema` flow is synchronous, the response carries the outcome, and projection-level `UNIQUE` constraints make duplicate-create attempts return informative "already exists" errors that themselves confirm the prior commit.

**Command vocabulary at the storage boundary.** The `command` column is plain `TEXT`, not a database enum. Validity is enforced at the API request decoder against the domain-layer `SchemaCommand` enum. Command names evolve with product features and audit-log readability needs, and that evolution should not require database migrations. The data event log's `op` column remains a database enum (`set` | `delete`) because that vocabulary is fixed by the LWW design and will not grow.

**Decoder.** The decoder enforces both command membership and payload shape (see the *Payload* column above); if both pass, the row is appended to `schema_change_log` and the projection is mutated in the same transaction.

**Versioning.** A tenant's `schema_version` is the highest `seq` in `schema_change_log` for that tenant. This is what clients compare against in ADR-009 and what the server tags onto data events. Because `seq` is per-tenant (see *`schema_change_log` shape* above), each tenant's `schema_version` walks `1, 2, 3, …` densely — clients can iterate `N+1, N+2, …` without discovering gaps from sibling-tenant activity.

**Audit.** The schema change log is the audit record. "Who renamed the mileage field on Truck and when" is one row in `schema_change_log` filtered by tenant and entity. Command grain matches user intent — one user action, one row — so audit reads do not require reconstructing intent from per-cell events.

**Diff for upgrade.** When a client upgrades from `active_schema_version = V_old` to the server's current `V_new`, the diff is computed by reading `SELECT * FROM schema_change_log WHERE tenant_id = ? AND seq > V_old AND seq <= V_new` and reducing per `entity_id` into a structured narrative. Command grain makes this natural: one command per row, one row per user action. ADR-009 specifies the per-entity reduction.

**Permissions.** For the initial release there is no authentication and no role system; any user connected to a tenant can edit that tenant's schema while online. Permissions may be introduced in a later ADR once authentication is decided.

## Consequences

The entire category of offline concurrent schema-edit conflict disappears. There is exactly one source of truth for the schema at any moment.

Tombstones make `deactivate_*` cheap and recoverable: routine "remove this from the UI" actions don't drop data, don't release the name, and can be undone with an empty-payload `activate_*`. Users get a "this field is hidden but the data is preserved" UX without the system having to retain extra history.

Name reservation across tombstones is observable within a tenant: a `create_*` whose `name` collides with any existing row's name (active or tombstoned) is rejected as `name_reserved`. This is acceptable within a tenant boundary — the tenant's own users are entitled to know what names exist in their schema history.

The data projection is not coupled to schema visibility at fold time. Events targeting tombstoned fields apply normally to `*_field_values` and to the `properties` JSON on the entity row; UI visibility is decided at read time by joining against the schema projection (ADR-012). This avoids cross-log coupling at write time and keeps the data fold a pure function of the data event log. A consequence is that two clients can race — one tombstones a field while another emits values for it — and the data event is accepted regardless. Other clients hide the field at the read layer. This costs some wire traffic for events that will never be displayed; we accept it as the simpler design.

`delete_*` is the only command that destroys both data and the name reservation. It is intentionally awkward (type-the-name confirmation) so users do not reach for it when `deactivate_*` or `clear_*_field` would do.

The schema change log is append-only and command-grain — superficially similar to the data event log but operationally different. There is no fold, no LWW, no HLC. Per-tenant ordering is by `seq`. Server is the sole writer.

Schema projection tables are pure current state plus an `active` flag. They need no `introduced_in_version` / `removed_in_version` columns. Name uniqueness within scope is enforced by ordinary `UNIQUE` constraints across both states.

Users lose the ability to edit schema offline. For a maintenance-tracking app this is acceptable: schema evolution is an admin-adjacent activity that rarely happens in the field. Day-to-day field work does not require schema changes.

The server must reject any data event whose referenced fields do not exist in the current schema projection (in *either* lifecycle state — tombstoned fields are still valid targets; only `delete_*`-d ones are gone). ADR-009 addresses how clients handle the case where their cached schema is out of date.

Because there is no authentication yet, any client acting against a tenant can edit that tenant's schema. This is a deliberate simplification for the initial release. When authentication and roles are introduced, a follow-up ADR will restrict schema edits appropriately.
