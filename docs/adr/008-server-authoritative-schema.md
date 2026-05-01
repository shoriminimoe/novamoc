# ADR-008: Server-Authoritative Schema

## Status

Proposed

## Context

The user-defined schema (asset types, their fields, maintenance record types, their fields) could in principle be edited from any client at any time and propagated as events like any other data. This was our initial direction, but it introduces a large class of offline conflict cases that are genuinely hard to resolve well: two clients concurrently adding fields with the same name, one client renaming while another generates events against the field, concurrent type changes on a field with existing values, concurrent removal and use.

These conflicts are qualitatively different from data conflicts. A per-field LWW fold of "rename field X to Y" against "delete field X" produces a clearly wrong outcome no matter which wins. There is no natural CRDT for schema evolution that preserves user intent across arbitrary concurrent edits.

The alternative: make the schema server-authoritative. Clients read the schema but cannot modify it offline. Schema edits go through the server while online. This eliminates concurrent schema edits by construction.

This constrains the product. Users in the field cannot restructure their data model offline. In practice this is acceptable: schema edits are rare, deliberate, and typically performed at a desk. Day-to-day work (recording maintenance, inspecting assets, logging parts) uses the schema as it exists and is fully offline-capable.

The schema is the one part of the system that is deliberately not event-sourced (ADR-002). It is current-state with a monotonic version number. The trade-off is deliberate: event sourcing's strengths (offline writes, deterministic merge, audit) are strongest for data and weakest for schema evolution.

## Decision

The server is the sole authority for the schema. Schema state lives in the meta-schema tables introduced in ADR-005 (`asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields`); these tables hold *current* state directly. Mutations are issued by clients as commands and recorded server-side in an append-only `schema_change_log` for audit and upgrade-diff purposes. The change log is not folded into the projection; it is a record of what happened, not the source of the projection's state.

**Command-vs-event split.** Any client may POST a schema-change command to `/schema` while online. The server validates the command against the current projection, applies the corresponding mutation, and appends one row to `schema_change_log`, all in a single transaction. The requesting client does not reflect the change locally until the corresponding broadcast arrives over the normal post-commit notification path; the round-trip is the acknowledgement. There is no local optimistic write for schema and no pending-schema queue. Offline clients cannot edit schema (ADR-001).

**Lifecycle on schema entities.** Both type rows and field rows carry an `active: BOOLEAN` column. A row is *active* when `active = true` and *tombstoned* when `active = false`. The entity `id` is stable across the lifecycle. Reusing a tombstoned name resurrects the existing row rather than creating a new one. `UNIQUE(tenant_id, name)` on type tables and `UNIQUE(tenant_id, parent_type_id, name)` on field tables apply across both states — a name is reserved by an entity for the entity's lifetime.

**Five command verbs per entity.** Commands are named `<verb>_<entity_kind>` in a single flat enum (`activate_asset_type`, `clear_maintenance_record_type_field`, etc.). The verbs are orthogonal intents:

| Command | Schema row | Data values | Name reserved | Confirmation |
|---|---|---|---|---|
| `activate_*` | created or resurrected | unchanged | yes | standard |
| `update_*` | properties modified | unchanged | yes (rename validated) | standard |
| `deactivate_*` | tombstoned | preserved | yes | standard |
| `clear_*_field` | unchanged | wiped (one field) | yes | "are you sure?" |
| `delete_*` | hard-deleted | wiped + cascaded | released | type-the-name |

`deactivate_*` is the routine "remove this from the UI" path: data is preserved, the name stays reserved, and the entity can be resurrected. `clear_*_field` empties the per-field projection (`*_field_values` rows for that field) and strips the field's key from each affected entity's `properties` JSON, but leaves the schema row alone. `delete_*` is admin-tier and terminal: the schema row is hard-deleted, all dependent data is wiped (cascaded from types to fields and entities), and the name is released for reuse. `clear` exists only on `*_field` entities — types do not have a field-value notion.

**Per-command semantics** apply uniformly across entity kinds:

- `activate_*` is create-or-resurrect. The server infers the operation from projection state; the client never declares it. The rule is the same for every entity kind:

  | Projection state | Empty payload | Non-empty payload |
  |---|---|---|
  | Missing | reject — "definition required to create" | create from payload |
  | Tombstoned (`active = false`) | resurrect (flip `active = true`, inherit existing definition) | reject — "name is held by a tombstoned entity; resurrect inherits its existing definition. Submit empty payload to resurrect, then follow with `update_*` to change properties." |
  | Active | no-op (idempotent ack) | reject — "use `update_*`" |

  This preserves freeze-on-resurrect: resurrection inherits the existing definition unchanged. Property changes after resurrection require a follow-up `update_*`.
- `update_*` modifies properties. Allowed regardless of `active` state. Renames are an `update` with a new `name`; the projection's `UNIQUE(tenant_id, [parent_id,] name)` constraint catches conflicts.
- `deactivate_*` sets `active = false`. Data values stay populated; the JSON key stays in `properties` on every affected entity row. Visibility is a UI concern resolved at read time (`WHERE active = true`).
- `clear_*_field` wipes `*_field_values` rows for that `field_id` and removes the field's key from each affected `properties` JSON. Idempotent.
- `delete_*` hard-deletes the projection row, cascades dependent rows (a type-level delete removes all of its fields and all entities of that type along with their values), and frees the name.

**Resurrection freezes properties.** An `activate_*` against a tombstoned entity carries an empty payload; the existing definition (data type, validation rules, etc.) is restored as-is. Property changes after resurrection require a follow-up `update_*` command. This keeps each command's semantics small.

**Reads.** Clients fetch the current schema projections from the server (filtering on `active = true` or carrying the flag through per the use case) and cache them locally. The cached projections are available offline for data-event generation, validation, and rendering forms.

**`schema_change_log` shape.** One row per accepted command. Columns: `seq` (BigInt PK, autoincrement, globally monotonic), `tenant_id`, `command` (TEXT — see *Command vocabulary at the storage boundary* below), `entity_id` (UUID — the type or field the command targets), `payload` (JSON, structured per command), `committed_at`, and `actor_id` (NULL until auth lands). An `idx_schema_change_log_tenant_seq (tenant_id, seq)` index supports per-tenant streaming for upgrade diffs. There is no application-level idempotency key: the `POST /schema` flow is synchronous, the response carries the outcome, and projection-level `UNIQUE` constraints make duplicate-create attempts return informative "already exists" errors that themselves confirm the prior commit.

**Command vocabulary at the storage boundary.** The `command` column is plain `TEXT`, not a database enum. Validity is enforced at the API request decoder against the domain-layer `SchemaCommand` enum. Command names evolve with product features and audit-log readability needs, and that evolution should not require database migrations. The data event log's `op` column remains a database enum (`set` | `delete`) because that vocabulary is fixed by the LWW design and will not grow.

**Payload conventions.** Each command has a structured payload shape, validated at the decoder:

| Command | Payload contents |
|---|---|
| `activate_*` | Empty object resurrects a tombstoned entity. Non-empty object creates a missing entity from the full definition (`name`, `data_type`, `validation`, parent ids). The server picks the operation from projection state; see *Per-command semantics* above. |
| `update_*` | Object containing only the changed properties. |
| `deactivate_*` | Empty object. |
| `clear_*_field` | Empty object. |
| `delete_*` | Empty object. |

The decoder enforces both command membership and payload shape; if both pass, the row is appended to `schema_change_log` and the projection is mutated in the same transaction.

**Versioning.** A tenant's `schema_version` is the highest `seq` in `schema_change_log` for that tenant. This is what clients compare against in ADR-009 and what the server tags onto data events. Because `seq` is globally monotonic across tenants, per-tenant version numbers are sparse — a tenant whose neighbour committed many changes will see its own version jump. This is acceptable for a developer/server-internal identifier; if a user-facing per-tenant counter is ever needed it can be added later.

**Audit.** The schema change log is the audit record. "Who renamed the mileage field on Truck and when" is one row in `schema_change_log` filtered by tenant and entity. Command grain matches user intent — one user action, one row — so audit reads do not require reconstructing intent from per-cell events.

**Diff for upgrade.** When a client upgrades from `active_schema_version = V_old` to the server's current `V_new`, the diff is computed by reading `SELECT * FROM schema_change_log WHERE tenant_id = ? AND seq > V_old AND seq <= V_new` and reducing per `entity_id` into a structured narrative. Command grain makes this natural: one command per row, one row per user action. ADR-009 specifies the per-entity reduction.

**Permissions.** For the initial release there is no authentication and no role system; any user connected to a tenant can edit that tenant's schema while online. Permissions may be introduced in a later ADR once authentication is decided.

## Consequences

The entire category of offline concurrent schema-edit conflict disappears. There is exactly one source of truth for the schema at any moment.

Tombstones make `deactivate_*` cheap and recoverable: routine "remove this from the UI" actions don't drop data, don't release the name, and can be undone with an empty-payload `activate_*`. Users get a "this field is hidden but the data is preserved" UX without the system having to retain extra history.

Name reservation across tombstones is observable within a tenant: an `activate_*` probe with a non-empty payload distinguishes "name free" (accepted as a create) from "name held by a tombstoned entity" (rejected with the resurrect-or-update guidance). This is acceptable within a tenant boundary — the tenant's own users are entitled to know what names exist in their schema history.

The data projection is not coupled to schema visibility at fold time. Events targeting tombstoned fields apply normally to `*_field_values` and to the `properties` JSON on the entity row; UI visibility is decided at read time by joining against the schema projection (ADR-012). This avoids cross-log coupling at write time and keeps the data fold a pure function of the data event log. A consequence is that two clients can race — one tombstones a field while another emits values for it — and the data event is accepted regardless. Other clients hide the field at the read layer. This costs some wire traffic for events that will never be displayed; we accept it as the simpler design.

`delete_*` is the only command that destroys both data and the name reservation. It is intentionally awkward (type-the-name confirmation) so users do not reach for it when `deactivate_*` or `clear_*_field` would do.

The schema change log is append-only and command-grain — superficially similar to the data event log but operationally different. There is no fold, no LWW, no HLC. Per-tenant ordering is by `seq`. Server is the sole writer.

Schema projection tables are pure current state plus an `active` flag. They need no `introduced_in_version` / `removed_in_version` columns. Name uniqueness within scope is enforced by ordinary `UNIQUE` constraints across both states; reusing a name resurrects the existing entity.

Users lose the ability to edit schema offline. For a maintenance-tracking app this is acceptable: schema evolution is an admin-adjacent activity that rarely happens in the field. Day-to-day field work does not require schema changes.

The server must reject any data event whose referenced fields do not exist in the current schema projection (in *either* lifecycle state — tombstoned fields are still valid targets; only `delete_*`-d ones are gone). ADR-009 addresses how clients handle the case where their cached schema is out of date.

The globally-monotonic `seq` will become a sharding consideration if the server ever needs to scale beyond a single SQLite file. Future ADR if and when that materializes.

Because there is no authentication yet, any client acting against a tenant can edit that tenant's schema. This is a deliberate simplification for the initial release. When authentication and roles are introduced, a follow-up ADR will restrict schema edits appropriately.
