# ADR-009: Require Clients to Accept Schema Changes Before Sync Resumes

## Status

Accepted (2026-05-28)

## Context

With the schema server-authoritative (ADR-008), clients cache a schema version locally. When the server's schema version advances, clients must at some point pick up the new version. Two broad approaches:

**Tolerate version skew.** Server retains historical schema versions and validates incoming events against the version the client was on. Clients upgrade at their convenience. This gives users control over when their forms change but requires the server to reconstruct and validate against arbitrary historical schemas.

**Require upgrade before sync.** Server only ever validates against the current schema. Clients whose cached schema is stale cannot sync until they accept the upgrade. Users may continue working locally against the old schema, generating events into their local event log, but those events do not propagate until they upgrade.

The second approach trades some user convenience for substantial server simplification. It also creates a natural invariant: every event the server accepts is, by construction, valid against the schema at the time of acceptance. The event log is therefore internally consistent with respect to schema — there are no "events referencing removed fields" to worry about on the server side.

Users do not lose the ability to finish what they're doing before upgrading: local event generation continues to work, and events accumulate in the pending queue. The upgrade is a deliberate action with an opportunity to review changes and reconcile pending events against the new schema locally.

## Decision

A client may sync data only while its cached schema version matches the server's current schema version. When the server's schema advances, the client transitions to a blocked state; sync resumes only after the user accepts the upgrade.

**Version tracking.** The server holds a monotonic `schema_version`. The client tracks its `active_schema_version`. Both are advertised in sync protocol messages.

**Notification.** When the server commits a schema change, it broadcasts a `schema_changed` message over the WebSocket (ADR-013) to all connected clients for that tenant. Offline or disconnected clients discover the mismatch on their next HTTP sync attempt.

**Per-event schema-version tagging.** `schema_changed` lives outside the event log and has no `seq`, so its delivery cannot be strictly ordered against in-flight event broadcasts that carry post-change `seq` values. To make ordering non-load-bearing, every event the server broadcasts is tagged with the `schema_version` that was active when the event was accepted (ADR-013). The client gates application on that tag: any event with `schema_version > active_schema_version` is held in a post-change buffer rather than applied or rejected. Whichever signal arrives first — the explicit `schema_changed` notification or a tagged post-change event — drives the client into blocked state and the same upgrade flow. After the user accepts the upgrade, buffered events are applied (or surfaced as part of the same reconciliation pass that handles pending local events).

**Blocked state.** While blocked, the client:
- Stops sending events to the server
- Stops applying events from the server: any in-flight events tagged with a newer `schema_version` are held in a post-change buffer rather than applied to projections or rejected (the WebSocket remains open for `schema_changed` and heartbeats)
- Allows the user to continue generating events locally; local events accumulate in the pending-event queue
- Displays a non-intrusive UI affordance indicating a schema upgrade is available

**Upgrade flow.** When the user accepts:
1. Client fetches the new schema projection from the server
2. Client requests rows from `schema_change_log` with `seq > active_schema_version AND seq <= server_version` for the tenant and reduces them per `entity_id` using the diff narrative below. Command grain makes this a single pass.
3. Client validates each pending event against the new schema
4. Events referencing `delete_*`-d fields, or fields with incompatible property changes (e.g., a type change that invalidates the existing value), are surfaced to the user for reconciliation. Events targeting merely `deactivate_*`-d (`active = false`) fields are not invalid — the field still exists, just hidden — so they pass through without user intervention.
5. Surviving pending events are sent; server acknowledges
6. Client's `active_schema_version` is updated to the server's current version
7. Buffered post-change events (those tagged with the new version that arrived during the block) are now applied in `seq` order
8. UI re-renders against the new schema

**Diff narrative.** For each `entity_id` touched in `(V_old, V_new]`, the per-entity reduction picks the most recent terminal state and summarizes the path to it:

| Sequence ending in… | Resulting label |
|---|---|
| `activate` (no later `deactivate` or `delete`) | "Added" |
| `deactivate` (currently tombstoned) | "Hidden" |
| `delete` | "Removed" |
| `update` with a name change | "Renamed" |
| `update` (other property changes) | "Modified" |
| `clear` (fields only) | "Field values cleared" |
| `activate → deactivate → activate` | "Restored" |

Compound paths fold to a single effective label. A user upgrading from N to N+5 sees one net change per entity, not five sequential ones.

**Pending-event reconciliation.** The flush of pending events must happen under the new schema, not the old. Local events generated before the upgrade are not automatically valid; they are subject to the validation pass in step 3. Reconciliation is a user-level decision *only* for events whose target has been `delete_*`-d or whose value is no longer valid against changed properties. Tombstones (`deactivate_*`) do not trigger reconciliation.

**Transport behavior during block.** The WebSocket remains connected during block state. `schema_changed` notifications and heartbeats traverse it as usual. The server may also continue to deliver post-change event broadcasts; these are tagged with the new `schema_version` and held in the client's post-change buffer rather than applied. Outbound events from the client are suspended until upgrade accept.

## Consequences

The server never needs to validate events against a historical schema version. This removes a meaningful class of server-side complexity and makes the invariant "every accepted event was valid against the schema when it was accepted" trivially true.

Users retain local autonomy: they can finish an in-progress task before accepting an upgrade. Their pending events do not silently vanish or change meaning — they are held locally until the user deliberately reconciles them against the new schema.

The product accepts that a user who defers upgrade indefinitely cannot participate in shared sync until they upgrade. For a small team this creates gentle pressure to stay current without the server enforcing anything heavy-handed.

Schema changes propagate in near-real time to connected clients via WebSocket notification, but apply only when users accept. This separates "awareness" from "application" — an important distinction for a tool used in the field.

The upgrade diff UX is load-bearing. Users need a clear view of what changed (fields added, removed, renamed) and what it means for their pending events. The schema change log (ADR-008) is command-grain, so each row is one user action and the per-entity reduction follows the table above directly.

A client offline for an extended period may return to find the schema has advanced several versions. The upgrade flow handles this transparently — the diff is still computed between the client's `active_schema_version` and the server's current version regardless of how many intermediate versions existed.

Tagging events with their accepted `schema_version` and gating client application on it removes the need to order `schema_changed` against in-flight event broadcasts. The server can commit a schema change between events N and N+1 without coordinating fan-out timing: the client correctly blocks and buffers regardless of which message arrives first. The invariant "every accepted event was valid against the schema at acceptance time" remains a server-side property; the client now has a corresponding invariant — "no event is applied against a schema version other than the one it was accepted under" — which is what makes the server invariant useful end-to-end.
