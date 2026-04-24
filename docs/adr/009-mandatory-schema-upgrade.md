# ADR-009: Require Clients to Accept Schema Changes Before Sync Resumes

## Status

Proposed

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

**Blocked state.** While blocked, the client:
- Stops sending events to the server
- Does not receive events from the server (the WebSocket remains open for `schema_changed` and heartbeats but carries no event traffic)
- Allows the user to continue generating events locally; local events accumulate in the pending-event queue
- Displays a non-intrusive UI affordance indicating a schema upgrade is available

**Upgrade flow.** When the user accepts:
1. Client fetches the new schema from the server
2. Client computes a diff against the cached schema using `introduced_in_version` and `removed_in_version`
3. Client validates each pending event against the new schema
4. Events referencing removed or incompatibly-changed fields are surfaced to the user for reconciliation (keep as note, discard, or map to a different field)
5. Surviving pending events are sent; server acknowledges
6. Client's `active_schema_version` is updated to the server's current version
7. UI re-renders against the new schema

**Pending-event reconciliation.** The flush of pending events must happen under the new schema, not the old. Local events generated before the upgrade are not automatically valid; they are subject to the validation pass in step 3. Reconciliation is a user-level decision — the user chooses what to do with events whose target has changed meaning.

**Transport behavior during block.** The WebSocket remains connected during block state. Only `schema_changed` notifications and heartbeats traverse it. Events in either direction are suspended until upgrade accept.

## Consequences

The server never needs to validate events against a historical schema version. This removes a meaningful class of server-side complexity and makes the invariant "every accepted event was valid against the schema when it was accepted" trivially true.

Users retain local autonomy: they can finish an in-progress task before accepting an upgrade. Their pending events do not silently vanish or change meaning — they are held locally until the user deliberately reconciles them against the new schema.

The product accepts that a user who defers upgrade indefinitely cannot participate in shared sync until they upgrade. For a small team this creates gentle pressure to stay current without the server enforcing anything heavy-handed.

Schema changes propagate in near-real time to connected clients via WebSocket notification, but apply only when users accept. This separates "awareness" from "application" — an important distinction for a tool used in the field.

The upgrade diff UX is load-bearing. Users need a clear view of what changed (fields added, removed, renamed) and what it means for their pending events. `introduced_in_version` and `removed_in_version` columns on field rows support this diff computation. Changes across multiple versions compact to a single effective diff; users upgrading from N to N+5 see one net change, not five sequential ones.

A client offline for an extended period may return to find the schema has advanced several versions. The upgrade flow handles this transparently — the diff is still computed between the client's `active_schema_version` and the server's current version regardless of how many intermediate versions existed.
