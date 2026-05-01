# ADR-013: HTTP and WebSocket as Interchangeable Sync Transports

## Status

Proposed

## Context

Sync needs to deliver events between client and server in two distinct regimes:

**Steady-state online.** A connected user wants to see their colleagues' events in near-real time. Polling on an interval wastes bandwidth and introduces latency floors. A push model is appropriate.

**Catch-up and reconnection.** A user who has been offline, or who just logged in, needs to receive a potentially large batch of events efficiently. A request/response model suits this: the client specifies its cursor, the server returns a bounded batch.

One transport optimized for one regime handles the other poorly. A WebSocket-only design handles catch-up awkwardly (streaming thousands of events one at a time after reconnection is slow and has no natural batching). An HTTP-only design introduces polling latency and wastes resources in the steady state.

Using both, with the same event protocol on both, gives each regime the transport it needs without maintaining two protocols.

## Decision

Sync uses two transports that carry the same event protocol: HTTP for catch-up and fallback, WebSocket for real-time delivery while online.

**HTTP `/sync`.** Used for:
- Initial sync after login (see also ADR-015)
- Catch-up on reconnection or at app start
- Pushing a batch of pending events
- Fallback when WebSocket is unavailable (corporate proxy, browser restriction, etc.)

Request carries the client's `tenant_id`, `node_id`, `active_schema_version`, current cursor, and any pending events to push. Response carries the server's current `schema_version`, the next cursor, and a bounded batch of events with `seq > cursor`. If the client's `active_schema_version` does not match the server's current version, the response signals schema-upgrade-required and no event flow happens (ADR-009).

**WebSocket `/sync/live`.** Used for steady-state real-time sync while online. The client opens the WebSocket after a successful HTTP catch-up has brought it current.

**Connection lifecycle (client coming online).**
1. Client sends HTTP `/sync` with its cursor. Server responds with all events since that cursor, plus the current server `seq`. Call this value `seq_catchup`.
2. Client applies the response — appending received events to its local event log and updating projections — then updates its cursor to `seq_catchup`.
3. Client opens WebSocket, sends a `hello` with `cursor=seq_catchup`, `node_id`, `active_schema_version`, `tenant_id`.
4. Server accepts and performs the gap-close → live-tail handoff described below.

The gap-close is essential. Without it, events that land in the window between HTTP response and WebSocket registration are lost.

**Gap-close → live-tail handoff (race-free).** The broadcaster task publishes events in `seq` order and tracks a `broadcaster_last_seq` — the highest seq it has fanned out. Subscriber registration runs under a short critical section that holds the subscriber registry lock:

1. Read `registration_seq := broadcaster_last_seq` (under lock).
2. Insert the subscriber into the registry marked **gap-closing**, with `gap_target = registration_seq`. Release the lock.
3. Outside the lock, run `SELECT ... FROM event_log WHERE tenant_id = ? AND seq > client_cursor AND seq <= gap_target ORDER BY seq` and stream those events to the client.
4. On completion, flip the subscriber's state to **live** (under the lock). The broadcaster delivers any event with `seq > gap_target` to this subscriber only while it is in live state.

Events with `seq <= gap_target` are covered by the gap-close query; events with `seq > gap_target` are covered by live-tail; the broadcaster never sends events to a subscriber in gap-closing state, so there is no duplication and no gap. `broadcaster_last_seq` only advances under the registry lock, so registration sees a coherent snapshot.

**Message types.**
```
// Client -> server
{ "type": "hello", "tenant_id": "...", "node_id": "...",
  "cursor": N, "active_schema_version": V }
{ "type": "event", "event_id": "...", "event": { ... } }
{ "type": "ping" }

// Server -> client
{ "type": "welcome", "server_seq": N, "schema_version": V }
{ "type": "event", "seq": N, "schema_version": V, "event": { ... } }
{ "type": "ack", "event_id": "...", "seq": N, "schema_version": V,
  "status": "applied" | "rejected", "reason": "..." }
{ "type": "schema_changed", "version": V }
{ "type": "pong" }
```

The `event_id` on client-sent messages is a client-generated identifier for the in-flight message, used by the client to correlate acks with pending events. It is distinct from the event's HLC (which is the canonical identity of the event in the log).

**Bidirectional event flow.** Events travel in both directions over the WebSocket. Client sends event messages and waits for an `ack` before marking the event as acknowledged in its local pending queue. The `UNIQUE (tenant_id, hlc)` constraint on the event log (ADR-011) makes replay idempotent, so a client whose WebSocket drops before an ack arrives can safely retry the event later over HTTP or a reconnected WebSocket.

**Broadcast ordering.** Server fan-out happens after the event is committed to the log, never inside the transaction. Broadcasts are sent in `seq` order — a single broadcaster task reads new log entries in order and fans them out to relevant tenant subscribers. This decouples commit from fan-out and guarantees ordered delivery to every subscriber.

**Schema version tagging on events.** Every event broadcast (over WebSocket or HTTP) carries the `schema_version` that was active on the server when the event was accepted. `schema_changed` lives outside the event log and has no `seq`, so its ordering relative to in-flight event broadcasts is not guaranteed. Rather than enforce that ordering, clients gate event application on `schema_version`: any received event with `schema_version > active_schema_version` is buffered locally and held until the client transitions through the upgrade flow (ADR-009). This makes the delivery order of `schema_changed` non-load-bearing — a client that receives a post-change event before the `schema_changed` notification arrives at the same conclusion (block, prompt for upgrade) via the version mismatch on the event itself.

**Heartbeats and dead connections.** Client sends `ping` every 20-30 seconds. Server treats a subscriber as dead if no `ping` has arrived in 60 seconds, closes the WebSocket, and removes the subscriber from the registry. Both sides implement reconnection with exponential backoff (1s, 2s, 4s, ..., capped at 30s).

**Reconnection.** On WebSocket close the client starts backoff. If the socket has been down for more than roughly 30 seconds on reconnect, the client does an HTTP `/sync` first to catch up efficiently, then opens a new WebSocket from the updated cursor. Short drops can reconnect and resume directly.

**Schema change notifications.** When the server commits a schema change, it broadcasts `schema_changed` to all connected subscribers of the affected tenant. Clients transition to blocked state (ADR-009). The WebSocket remains open but no events flow in either direction until the client's `active_schema_version` catches up. A client may also discover the change via the `schema_version` tag on a delivered event arriving before `schema_changed`; the response is the same (block, hold post-change events, prompt the user to accept the upgrade).

**HTTP `/schema`.** Schema mutations flow over a separate HTTP endpoint, not the data sync transports. The request body is a flat envelope:

```json
{
  "command": "activate_asset_type",
  "entity_id": "...",
  "payload": { ... }
}
```

`command` is one of the verb-prefixed names defined by `SchemaCommand` (ADR-008: `activate_*`, `deactivate_*`, `update_*`, `clear_*_field`, `delete_*`). The server's request decoder is responsible for validating that `command` is a known member of the enum and that `payload` matches the command's expected shape; it is also where the database stores `command` as plain TEXT. After decoder validation, the server validates the command against the current schema projection, applies the mutation, appends a row to `schema_change_log`, and returns the assigned `seq` (the new `schema_version`). The flow is synchronous — the response is the acknowledgement, and projection-level `UNIQUE` constraints surface duplicate-create attempts as informative errors. There is no offline queue and no fallback transport: schema commands are online-only by construction (ADR-001, ADR-008). Schema changes are surfaced to other clients via the `schema_changed` notification described above; the broadcast payload carries the new `schema_version`, and the command-grain change-log entries are fetched on demand during the upgrade diff (ADR-009).

**Transport interchangeability.** The wire format of an event is identical regardless of transport. The HTTP endpoint is not a fallback with a different protocol — it is the same protocol over a different pipe. We should routinely test with WebSocket disabled to ensure the application remains functional on pure HTTP, as corporate proxies and some browser configurations block WebSocket upgrades.

**Server-side subscriber registry.** The server maintains an in-process map of tenant_id -> set of connected WebSocket handles. Broadcasts consult this map. For the initial single-process deployment this is sufficient. Multi-process deployments will require an additional fan-out mechanism (options: polling the event log from each process, or an out-of-process pub/sub); this is out of scope for this ADR and would be addressed when multi-process deployment becomes necessary.

## Consequences

Steady-state online experience is real-time. Events propagate to other connected clients within tens to low hundreds of milliseconds, with no polling overhead.

Catch-up after offline periods is efficient. A client returning after hours offline fetches events in bounded batches over HTTP, not one-at-a-time over a freshly-opened WebSocket.

Having two transports doubles the surface for bugs. Keeping the wire format identical across transports is a mitigation: there is one protocol to get right, not two. Regular testing with WebSocket disabled verifies the HTTP path remains a first-class citizen.

Single-process subscriber registry is a soft constraint on initial deployment topology. For a small-team product this is not a practical limitation; should the need for multi-process deployment arise (for HA or scale), a follow-up ADR will address cross-process fan-out.

WebSocket authentication has its own considerations (browsers do not allow custom headers on WebSocket upgrades), but authentication as a whole is not yet designed and is out of scope (ADR-001 notes auth is deferred).
