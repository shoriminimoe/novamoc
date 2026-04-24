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

The server is the sole authority for the schema. The schema consists of the meta-schema tables introduced in ADR-005: `asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields`.

**Reads.** Clients fetch the schema from the server and cache it locally. The cached schema is available offline for event generation, validation, and rendering forms.

**Writes.** Schema mutations go through a dedicated online-only HTTP endpoint. The server validates, commits, assigns a new schema version number, and notifies connected clients (ADR-009).

**Offline behavior.** Any client may initiate schema edits while online. Clients have no notion of pending schema edits — schema changes are not queued locally for later replay, and they do not produce events in the data event log. If the user is offline, the schema-edit UI is unavailable or disabled.

**Versioning.** Each schema change increments a monotonic server-assigned version number. Individual field rows carry `introduced_in_version` and, for tombstoned fields, `removed_in_version`. This enables clients to compute the diff between two versions for display purposes (see ADR-009).

**Schema change audit.** The schema is not event-sourced, but schema changes are audited through a dedicated `schema_change_log` table on the server: one row per accepted schema mutation, capturing `tenant_id`, `schema_version`, `committed_at`, `actor_id` (populated once authentication exists; NULL for the pre-auth period), and a structured description of the change (added field, removed field, type change, rename). This table is append-only and is not synced to clients; it is an administrative/compliance record accessed through server-side tools. This gives schema the same audit property that the event log gives data, without imposing the event-sourcing machinery on a piece of state that is deliberately current-state (see Context).

**Permissions.** For the initial release there is no authentication and no role system; any user connected to a tenant can edit that tenant's schema while online. Permissions may be introduced in a later ADR once authentication is decided.

## Consequences

The entire category of offline concurrent schema-edit conflict disappears. There is exactly one source of truth for the schema at any moment.

The event log is simplified. Schema is not carried as events; it is a separate, simpler "fetch current state" resource. Every event in the event log, by construction, refers only to fields valid at the time of acceptance.

Users lose the ability to edit schema offline. For a maintenance-tracking app this is acceptable: schema evolution is an admin-adjacent activity that rarely happens in the field. Day-to-day field work does not require schema changes.

The server must reject any data event whose referenced fields do not exist in the current schema. ADR-009 addresses how clients handle the case where their cached schema is out of date — by forcing an upgrade rather than by maintaining historical schema versions on the server.

Because there is no authentication yet, any client acting against a tenant can edit that tenant's schema. This is a deliberate simplification for the initial release. When authentication and roles are introduced, a follow-up ADR will restrict schema edits appropriately.
