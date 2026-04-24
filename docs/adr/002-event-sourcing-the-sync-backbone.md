# ADR-002: Apply Event Sourcing to the Sync Backbone

## Status

Proposed

## Context

The sync layer of novaMOC carries the load-bearing responsibilities of the system: recording what has happened, propagating those happenings between participants, resolving concurrent changes deterministically, and providing a consistent view across offline and online participants. How this layer is conceived — what its data actually represents, what is authoritative, and what is derived — shapes every decision downstream of it.

Two broad mental models are available:

**Current-state model (CRUD).** The database stores "what is true now." Updates overwrite prior values. History is incidental, typically reconstructed from backups, audit columns, or changelog tables bolted on after the fact. This is the model most developers start with, and it works well when the application's questions about data are all in the present tense.

**Event-sourced model.** The database stores "what has happened" as an append-only sequence of events. Current state is a derived projection — a fold over the events relevant to a given entity. The event log is the source of truth; all other representations are disposable caches of it.

novaMOC has properties that align unusually well with event sourcing:

- Offline participants need to record changes locally before the server sees them, then propagate those changes later. These local records are events — facts about what the user did — even before the server has validated them against the canonical schema.
- Deterministic merge of concurrent changes across participants requires that all participants have the same ordered set of facts and apply the same resolution rule. An event log plus a deterministic fold fits this exactly.
- An audit history ("who changed the mileage on this asset and when, from what to what") is a natural requirement of maintenance tracking and falls out trivially from an event log.
- Materialized entity state may need to be rebuilt from time to time (projection bugs, schema corrections, disaster recovery). With an event log this is routine; without one, it is a manual migration every time.

The event-sourcing pattern is not a framework — it is a way of structuring data and reasoning about state. We adopt it as a pattern and a vocabulary, without introducing a heavy external dependency.

## Decision

The sync backbone of novaMOC is structured as an event-sourced system. The event log is the source of truth for all synchronized data. Current entity state is a projection derived by folding the event log under the rules in ADR-007.

We adopt the following vocabulary throughout subsequent ADRs:

- **Event.** An immutable record of a fact about what happened. Each event is stamped with a Hybrid Logical Clock (ADR-006) and carries an originating node id, a target entity and field, an operation (set or delete), and a value. Events are named by what they assert, not by what they command.
- **Event log.** The append-only sequence of events. Stored as a SQLite table named `event_log` (ADR-011). Server-side, the event log is canonical and authoritative. Client-side, it is a forward-looking mirror starting at the initial-sync cursor (ADR-015) — events prior to that cursor are implicit in the transferred projection — plus a pending queue of locally-generated events not yet acknowledged by the server. The server remains the system of record for full history.
- **Projection.** A derived view of state computed from the event log. The materialized entity tables (assets, maintenance records, and their associated field-value tables) and their JSON property columns are projections. Projections are disposable: they can be dropped and rebuilt from the event log at any time.
- **Fold.** The function that computes a projection's state from events. For novaMOC's primary projection, the fold is per-field last-write-wins keyed by HLC (ADR-007).
- **Command.** A request — typically arising from user interaction — to record an event. The client generates events locally in response to commands, appending them to its local event log and its pending queue. "Command" is useful as a conceptual marker for user intent but rarely needs to be a distinct object in code: a command's outcome, when accepted, is an event.

**Scope.** Event sourcing applies to all synchronized data: assets, maintenance records, and their user-defined field values. The schema (ADR-008) is not event-sourced — it is server-authoritative state that clients fetch, cache, and re-fetch on change. The schema has a monotonic version number but does not produce events in the log.

**Not a framework.** We do not adopt an event-sourcing library, enforce a layered ES architecture, or introduce aggregate-root scaffolding. What we adopt is the vocabulary, the mental model, and the guarantees that follow from structuring the sync backbone this way. Subsequent ADRs describe the concrete data structures and algorithms; this ADR frames the pattern they collectively implement.

## Consequences

The event log is the system of record. Entity tables and their JSON-property read columns are caches. If they diverge from the log, the log wins and the caches are rebuilt by re-folding.

New read shapes are new projections. Reporting views, search indexes, dashboards, and analytics — any of these can be added later as consumers of the event log without disturbing the write path. The discipline of "writes produce events; reads project into whatever shape the consumer needs" keeps the two decoupled.

Temporal queries are available for free. "What did this asset look like on March 1?" is a fold over events with HLC at or before that instant. The capability is latent; no additional machinery is needed if and when a feature requires it.

Audit is the log. "Who changed the mileage on truck 47 and when, and from what to what?" is a filter and ordering over the event log. No separate audit table, triggers, or application-level logging is required.

Testing is event-centric. The sync engine is testable by constructing event sequences and asserting on the resulting projection. No database, no network, and no framework is required for correctness tests of the fold, the HLC comparator, or the schema gate.

Events are immutable. Corrections happen by recording new events — for example, a subsequent set of a field to the correct value — not by editing or deleting past events. Operationally this can feel unfamiliar, but it is the discipline that makes the rest of the guarantees hold.

Event schema evolution is a concern we will have to address eventually. As the system changes over time, the shape of events may change. When it does, old events in the log must still be interpretable. Known techniques (versioned events, upcasters, tolerating missing fields) exist. A future ADR will address the specific approach when it becomes necessary; for the initial release, it is not yet required.

Storage grows. The event log is not pruned. At the target scale — small teams, modest write volume — this is comfortably within SQLite's operating range for years of continuous use. Compaction or archival policies are out of scope for now and would be addressed in a future ADR if growth becomes a concern.
