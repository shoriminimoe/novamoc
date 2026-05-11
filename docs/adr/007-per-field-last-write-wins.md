# ADR-007: Use Per-Field Last-Write-Wins as the Projection Fold

## Status

Accepted

## Context

Given an event log (ADR-002, ADR-011) that orders events by HLC (ADR-006), we need a deterministic function for folding events into the current-state projection. When two clients generate events against the same data offline and later sync, the fold must produce the same projection on every participant. Candidate folds:

**Per-record LWW.** The entire record is the fold unit. If one user edits the mileage and another edits the next-service date on the same asset, one user's event is lost to the other in the projection. This produces surprising behavior for users whose edits touched different fields.

**Per-field LWW.** Each field is folded independently. Two users editing different fields of the same record both succeed — both events contribute to the projection. Two users editing the same field have the later HLC win in the projection. Matches the realistic patterns of concurrent edits in a maintenance-tracking app.

**CRDT merges (e.g. Automerge).** Rich merge semantics for text and data structures. Valuable when multiple users are editing the same free-form text concurrently, less valuable for structured business data where there is no meaningful merge of `45,120` and `45,130` as mileage readings — one is correct and the most recent authoritative write is the right answer.

**Operational transformation / server-authoritative resolution.** Requires the server to compute merges and reject contributions, which breaks the offline-first model and contradicts the deterministic-fold-on-every-participant property we want.

For a small maintenance team with structured data, per-field LWW gives intuitive results with minimal machinery. Two mechanics working on the same truck but different fields both see their edits preserved in the projection. The same-field case (rare) folds to the later write, which is generally what users expect.

Note that per-field LWW is a property of the fold, not of the event log. The log records all events, winners and losers both. A "lost" event is not deleted; it is simply not the one chosen by the fold for the projection value. This preserves history and keeps alternate projections (audit views, debugging, future features) possible.

## Decision

The projection fold is per-field last-write-wins, keyed by HLC (ADR-006). The fold is deterministic: given the same set of events, every participant computes the same projection.

**Unit of fold.** Each user-defined field on each entity is a fold unit. Fixed entity columns (name, type_id, etc.) are also fold units at per-column grain.

**Fold rule.** For a given entity and field, the projection value is that of the event with the highest HLC. HLC comparison is lexicographic on the serialized form.

**Tiebreaking.** HLCs include a node id, so identical HLCs from different nodes are impossible by construction. Identical HLCs from the same node cannot occur because local generation monotonically advances the counter within a physical-time value.

**Deletions.** Deletes are represented as tombstone events carrying an HLC. A delete event with a higher HLC than a set wins (the field becomes cleared/null in the projection, or the entity becomes deleted). A set event with a higher HLC than a delete wins (the field is restored in the projection). Tombstone events are retained in the log indefinitely for now; garbage collection is out of scope for this ADR.

**Determinism.** Given the same set of events, every participant computes the same projection. The server is not an authoritative resolver — it applies the same fold every client does.

## Consequences

Users experience the projection as intuitive: their events to a field they touched are preserved in the projection unless someone else has a later event for the same field. The common case of two people editing different aspects of the same record works correctly with no conflict surface.

The same-field conflict case (rare) silently folds to the later event with no UI surface. We accept this as the right default for structured data. If a use case emerges where field-level conflict UI is needed, it can be added later without changing the underlying fold rule — the event log preserves the losing events and can be surfaced in a dedicated projection.

We do not get rich merge semantics for free-form text. If a field ever needs them (for example, multi-author maintenance notes), it can be modeled with a CRDT-valued field type while leaving the rest of the system on LWW. No such field is planned now.

Per-field folding requires events at field grain. ADR-012 describes how this grain is achieved in the event log and in the projection tables while preserving the JSON-property read model from ADR-005.
