# ADR-010: Hand-Roll the Sync Engine

## Status

Proposed

## Context

Several mature local-first sync engines exist and were evaluated:

- **ElectricSQL.** Postgres-only on the server. Not compatible with our SQLite server choice (ADR-004).
- **PowerSync.** Postgres, MySQL, MongoDB on the server. No SQLite.
- **Zero (Rocicorp).** Postgres only.
- **Replicache (Rocicorp).** Database-agnostic because the developer writes the push and pull endpoints. Compatible with SQLite on the server but effectively a client-side framework; a substantial portion of the sync logic still has to be written.
- **Evolu.** Uses SQLite on both sides. Built around end-to-end encryption with a dumb relay, which conflicts with our server-authoritative schema model (ADR-008) that requires the server to read and validate events.
- **cr-sqlite.** A SQLite extension that adds CRDT semantics to tables directly. Python bindings exist. A smaller, younger project than the Postgres-backed options, with a narrower community.

No off-the-shelf engine fits our constraints cleanly: SQLite on the server, Python/Litestar, server-authoritative schema with server-side validation of events, mandatory schema upgrade instead of version-tolerant sync, hand-controlled tenant isolation, and an event-sourced backbone (ADR-002) where we want full control over the event log's shape and semantics.

The sync protocol we need is tractable in scope: an append-only event log with HLC ordering (ADR-006), per-field LWW as the fold (ADR-007), a version-check gate (ADR-009), and two interchangeable transports (ADR-013). Estimated size: a few hundred lines of Python on the server, a few hundred lines of TypeScript on the client.

## Decision

We will implement the sync engine ourselves rather than adopt an existing framework.

The implementation follows the protocol described across ADR-006 (HLC), ADR-007 (LWW fold), ADR-009 (schema gating), ADR-011 (event log), ADR-012 (event grain and projections), and ADR-013 (transports). No external sync engine is introduced as a dependency.

HLC generation, fold computation, event log append, and fan-out are built from primitives: SQLite, Litestar, and standard Python libraries on the server; SQLite-WASM and standard browser APIs on the client.

## Consequences

We own the sync layer end to end. This is a material investment — an initial implementation plus ongoing maintenance — but the protocol is well-understood and the scope is bounded. We are not betting on a specific external project's longevity, roadmap, or compatibility with our other choices.

We retain full control over tenant scoping, server-side validation, schema-gate behavior, and error reporting. These are where our requirements diverge most from off-the-shelf engines, and hand-rolling lets us fit them cleanly rather than working around framework assumptions.

The event-sourcing discipline of ADR-002 is easier to uphold with a hand-rolled engine. We can make the event log the explicit center of the design rather than adapting around a framework's implicit data model.

We forego reactive-query infrastructure that some engines provide out of the box. We can implement a small pub/sub layer on the client that invalidates queries on projection-table writes; the cost is modest (on the order of 50 lines).

We should write a tight test suite for the sync protocol, exercising HLC ordering, the LWW fold, idempotent replay, schema-gate transitions, and reconnection catch-up. Because this code is foundational and event-centric, tests here return their cost many times over — an event-sequence test with an in-memory event log exercises the core without requiring a database or a network.

If, later, a sync framework emerges that fits our constraints well (SQLite server, server-authoritative schema, Python-friendly, event-log-centric), revisiting this decision is cheap: the protocol is simple enough to migrate to or from.
