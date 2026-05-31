# Design: client repository-layer spike (Kysely vs Drizzle vs hand-rolled vs raw)

## Status

Spiked 2026-05-30 (issue #143, E1.4 of Epic 1 / #138). **Decision: hand-rolled
typed functions with inline SQL.** Unblocks E1.9 (the repository build-out),
which implements the full layer in the chosen style. ADR-003 (SQLite-WASM over
OPFS) is the storage substrate all four candidates sit on; this spike does not
revise any ADR.

The throwaway spike code lives on branch `spike/143-repo-layer` at commit
`569c28c` (`src/js/web/spike/`) and is deliberately **not merged** — only this
doc lands on `main`. The spike is reproducible from that commit: `cd
src/js/web/spike && npm install`, then `CANDIDATE=<name> npx vite build` per
candidate.

## Problem

E3 (asset UI) and E4 (record UI) read and write through a typed client-side
repository layer over the local SQLite-WASM database. The *shape* of that layer
— hand-rolled typed functions, a query builder (Kysely), an ORM (Drizzle), or
raw `db.exec` + type assertions — is load-bearing: it sets the ergonomics of
every feature that touches local data, and a wrong pick is expensive to undo
once E3/E4 are built on it. The Epic 1 spec (§"Q5") deferred the choice to this
spike rather than guessing at planning time.

The deciding constraint is that novaMOC is local-first (ADR-003): the entire
abstraction layer ships **to the browser**, on top of the already-heavy
SQLite-WASM blob. Bytes and cold-start parse cost are real, not amortized over a
server fleet. So this is a four-way trade between bundle weight, compile-time
type safety, and authoring ergonomics — measured against real code, not
asserted.

## Method

Each candidate implements the identical representative subset against the same
table shapes (mirrored from the server projections in
`src/py/novamoc/db/models/data/_asset.py`):

- `assets` — `(tenant_id, id)` composite PK, a `properties` JSON column
  (ADR-012/ADR-019), `deleted` flag, `row_state_hlc`.
- `asset_field_values` — `(tenant_id, asset_id, field_id)` PK EAV/LWW table with
  an `hlc` ordering column.

Operations per candidate: `assets` upsert (ON CONFLICT) + `listByType` +
`getById`; `asset_field_values` upsert + `listByEntity`; plus one
`assets × asset_field_values` join. All four sit on a common `WasmDB.exec(...)`
shim that mirrors the `@sqlite.org/sqlite-wasm` OO API — the real WASM blob is
identical weight under all four, so it is excluded from the delta and the shim
(~15 lines, inlined into every bundle) cancels out of the comparison.

Bundle weight: each candidate is built in isolation with `vite build` (esbuild
minify, ES2022, ES-module lib mode, one entry per candidate that exercises every
function so nothing tree-shakes away). Sizes below are the emitted `bundle.js`.
Type safety: a deliberate misspelled-column error is induced in each and run
through `tsc --strict`. Build weight: `tsc` wall time per candidate and the
codegen step (Drizzle only).

Toolchain measured against: `vite@6.4.2`, `typescript@5.7.3`, `kysely@0.27.6`,
`drizzle-orm@0.38.4`, `drizzle-kit@0.30.6`, Node 25.8. (The spike pins Vite 6 /
TS 5.7 for a clean isolated harness; the web app itself is on Vite 8 / TS 6, but
the measured library deltas are a property of the libraries, not the bundler
version.)

## Findings

### Bundle-size impact

Built in isolation, minified, ES-module lib output. `gzip -9` is the wire-cost
proxy that matters; raw is the parse/eval surface.

| Candidate     | raw bytes | gzip bytes | gzip delta vs hand-rolled |
| ------------- | --------: | ---------: | ------------------------: |
| raw           |     2,281 |        739 |                      −176 |
| **hand-rolled** | **3,187** |    **915** |                  **base** |
| Drizzle ORM   |   105,858 |     23,813 |                  +22,898  |
| Kysely        |   293,959 |     48,449 |                  +47,534  |

The two dependency-bearing candidates are in a different order of magnitude.
Drizzle adds ~23 KB gzip over hand-rolled; Kysely adds ~47 KB gzip — roughly
2× Drizzle and ~53× the hand-rolled abstraction's own footprint. Hand-rolled and
raw are rounding error: the abstraction is just the SQL strings plus mapping
functions, so the bundle is essentially the SQL text itself. (Kysely is heavier
than Drizzle here partly because the compile-only path still pulls the dialect
machinery — `SqliteAdapter`/`SqliteQueryCompiler`/`SqliteIntrospector` — and
Kysely's query-builder runtime is largely un-tree-shakeable once any builder
method is reachable.)

### Type-safety

A misspelled column / wrong row shape was induced in each and run through `tsc
--strict`:

| Candidate     | Misspell caught at compile time? | Diagnostic |
| ------------- | -------------------------------- | ---------- |
| **hand-rolled** | **Yes** | `TS2352` — object literal doesn't overlap `Asset` (mapping function is the typed chokepoint) |
| Kysely        | Yes | `TS2345` — `"tennant_id"` not assignable to `ReferenceExpression<DB, "assets">` |
| Drizzle       | Yes | `TS2551` — `Property 'tennantId' does not exist … Did you mean 'tenantId'?` |
| **raw**       | **No** | compiles clean — `as unknown as Asset[]` swallows the error entirely |

Three of four catch the error; **raw does not** — the `as` cast at the boundary
is precisely the hole that defeats the type checker, and a misspelled column in
the SQL surfaces only as `undefined` at runtime. Kysely and Drizzle catch it at
the *query* site (you can't even name a bad column). Hand-rolled catches it at
the *mapping* site rather than the SQL site: the inline SQL string is itself
unchecked (a typo in `SELECT tennant_id` is invisible), but the hand-written
`rowToAsset` mapper is a fully-typed object literal, so any drift between the
SQL columns and the domain type is caught there. This is weaker than Kysely/
Drizzle (which check the column name directly) but categorically stronger than
raw, because every read funnels through a typed mapper instead of a blind cast.

### Join ergonomics

The `assets × asset_field_values` join (composite-key ON clause) was written in
all four:

- **Hand-rolled** — the join is one SQL string with explicit aliases
  (`JOIN asset_field_values v ON v.tenant_id = a.tenant_id AND v.asset_id =
  a.id`) plus a result type and a mapper. The SQL is exactly what you'd write by
  hand and reads clearly; the cost is the hand-written `AssetWithField` result
  type and its mapper.
- **Kysely** — `.innerJoin(..., (j) => j.onRef('v.tenant_id','=','a.tenant_id')
  .onRef('v.asset_id','=','a.id'))` with a `.select([...])` of aliased columns.
  The result type is *inferred* from the select list — no hand-written shape.
  Verified the compiler emits the correct parameterized SQL. Most ergonomic for
  evolving joins, at the cost of a builder DSL to learn.
- **Drizzle** — `.innerJoin(table, and(eq(...), eq(...)))` with a `.select({...})`
  projection object; result type inferred. Comparable to Kysely; the `eq`/`and`
  helper style is slightly more verbose than Kysely's `onRef` for multi-column
  ON clauses.
- **Raw** — same SQL string as hand-rolled but the result is `as unknown as
  AssetWithField[]`; ergonomically trivial to write, but column/shape drift is
  unguarded.

For this codebase the join shapes are stable and few (assets ⋈ field values,
records ⋈ field values), so the inferred-result-type advantage of the query
builders is real but small — a handful of hand-written result types, written
once.

### Build / dev-loop weight

Per-candidate `tsc --strict` wall time (isolated tsconfig, single entry):

| Candidate   | tsc wall | Codegen step |
| ----------- | -------: | ------------ |
| hand-rolled |   2.22 s | none |
| raw         |   2.44 s | none |
| Kysely      |   3.02 s | none (schema is a hand-written TS interface) |
| Drizzle     |   3.59 s | `drizzle-kit generate` — required |

Hand-rolled and raw are the lightest on the type checker. Kysely adds ~0.8 s
(its conditional-type-heavy query builder). Drizzle is heaviest on `tsc` *and*
adds a mandatory codegen step: `drizzle-kit generate` reads `drizzle_schema.ts`
and emits a DDL migration (verified — it produced a correct
`CREATE TABLE assets (… PRIMARY KEY(tenant_id, id))` and the field-values
table). That codegen is a genuine extra moving part in the dev loop and, more
importantly, it wants to **own** the DDL — which collides with novaMOC's plan to
build the local DDL by hand in #141 to mirror the server projections exactly.

### JSON column handling (`properties`, ADR-012/ADR-019)

SQLite has no JSON type — `properties` is TEXT holding serialized JSON, and the
question is who owns the (de)serialization:

- **Drizzle** — best. `text('properties', { mode: 'json' }).$type<Record<string,
  unknown>>()` makes the column typed *and* auto-(de)serialized: call sites pass
  and receive a plain object, no `JSON.stringify`/`parse` anywhere. This is the
  one place Drizzle is clearly ahead.
- **Hand-rolled** — `JSON.stringify` on write and `JSON.parse` on read live in
  the typed mapper, in exactly one place per table. Explicit but contained; the
  mapper is already the chokepoint, so the JSON handling rides along for free.
- **Kysely** — the column is typed `string` in the `Database` interface and the
  builder won't serialize for you, so you `JSON.stringify` at the call site and
  `JSON.parse` in a deserialize helper — same manual handling as hand-rolled but
  spread across more call sites (every `.values({...})` stringifies inline).
- **Raw** — fully manual `JSON.parse`/`stringify`, untyped, easy to forget.

Drizzle's automatic JSON handling is a real ergonomic win, but for novaMOC the
JSON surface is small and centralized: `properties` on `assets`/`maintenance_
records` and `value_json` on the two `*_field_values` tables. The fold layer
(E1.5) already owns JSON parsing for the projection, so the repo's JSON
(de)serialization is a handful of `JSON.parse`/`stringify` calls in a few
mappers — not enough to justify Drizzle's ~23 KB gzip and its codegen step.

## Decision

**Hand-rolled typed functions with inline SQL.** It is within a rounding error
of the bundle-size floor (~0.9 KB gzip vs raw's 0.7 KB, and ~23–47 KB lighter
than the dependency-bearing options — the decisive factor given local-first
ships everything to the browser, ADR-003); it is the lightest on the type
checker with no codegen step; and unlike raw it is genuinely type-safe at the
read boundary, because every row funnels through a hand-written typed mapper
instead of a blind `as` cast. The query builders (Kysely/Drizzle) buy
column-name-level safety and inferred join result types, but novaMOC's query
surface is small and stable (a fixed handful of upserts, list-bys, and two
joins, all mirroring server projections being hand-built in #141), so that
upside is marginal here while the bundle and tooling costs are not. Drizzle's
automatic JSON handling is the one feature worth missing, but the JSON surface is
tiny and centralized in a few mappers, and Drizzle additionally wants to own the
DDL — colliding with the hand-built local schema. Hand-rolled wins on the axis
that matters most for a local-first client and loses only marginally on the
axes where the heavier options lead.

## Out of scope

- Implementing the full repository — that's E1.9, using this style.
- The server's persistence layer — unchanged (advanced-alchemy, ADR-004).
- A SQL-string lint/compile-check for the hand-rolled SQL — worth considering in
  E1.9 to close the one gap (unchecked column names *inside* the SQL string),
  e.g. a test that runs each statement against the real DDL at build time. Noted
  for E1.9, not decided here.

## References

- Issue #143 (E1.4); Epic 1 (#138); spike branch `spike/143-repo-layer` @
  `569c28c`.
- `docs/superpowers/specs/2026-05-30-epic-1-local-first-engine-design.md` §"Q5"
  (the deferral) and E1.9 (the gated build-out).
- ADR-003 (SQLite-WASM over OPFS), ADR-012 / ADR-019 (`properties` JSON column).
- Server projection shapes mirrored: `src/py/novamoc/db/models/data/_asset.py`.
