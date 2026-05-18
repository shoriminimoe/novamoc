# Schema Changes Catch-up Endpoint Design

## Status

Draft

## Purpose & scope

Add `GET /schema/changes?since=<seq>` — the streaming counterpart to `GET /schema` (snapshot). Returns the active tenant's `schema_change_log` rows with `seq > since` ordered ascending, in bounded batches, so a returning client can step forward through each schema mutation rather than re-fetching the whole snapshot. This is the server side of the ADR-009 upgrade-diff flow.

Out of scope:

- The client-side reduction of rows into a per-`entity_id` diff narrative (ADR-009 table). Server emits raw rows; client folds them.
- WebSocket `schema_changed` notification (ADR-013) and the client's blocked-state UX (ADR-009). Different transport, different surface.
- A real `actor_id`. Auth lands in M5; `actor_id` is emitted as `null` until then.

## HTTP contract

### Route

`GET /schema/changes`, mounted on the existing `SchemaController` (which already owns `/schema`).

Query parameters:

| Name | Type | Default | Bounds | Meaning |
|---|---|---|---|---|
| `since` | int | `0` | `>= 0` | Exclusive lower bound on `seq`. `since=0` returns the full per-tenant history. |
| `limit` | int | server default (see *Batch size*) | `1 <= limit <= max` | Page size cap. |

Tenant is resolved by `TenantContextMiddleware` (ADR-017) from the bearer token. No tenant ever appears in the URL or body. Layer 1 of `db._listeners` supplies the `WHERE tenant_id = ?` predicate on every read in the handler.

### Success response — 200 OK

```json
{
  "schema_version": 47,
  "changes": [
    {
      "seq": 12,
      "command": "create_asset_type",
      "entity_id": "8c1d…",
      "payload": {"name": "Truck"},
      "committed_at": "2026-05-18T10:14:22.193Z",
      "actor_id": null
    },
    {
      "seq": 13,
      "command": "create_asset_type_field",
      "entity_id": "f0a1…",
      "payload": {"parent_id": "8c1d…", "name": "VIN", "data_type": "text"},
      "committed_at": "2026-05-18T10:14:23.041Z",
      "actor_id": null
    }
  ],
  "next_since": 13,
  "has_more": true
}
```

Headers:

```
Content-Type: application/json
```

(No ETag. The resource is page-shaped — different `(since, limit)` yields different bodies — and clients drive freshness via `next_since` / `has_more` plus an out-of-band ETag on `GET /schema` when they decide to re-snapshot.)

Field-by-field:

- `schema_version` — the tenant's current `MAX(seq)` (`0` for empty). Snapshot-consistent with `changes`: both reads share one SQLite WAL transaction. A client that wants the simplest "have I caught up?" check compares `next_since == schema_version`.
- `changes` — rows with `seq > since AND seq <= schema_version`, ordered ascending by `seq`, capped at `limit`.
  - `seq` — per-tenant dense integer (issue #17, closed).
  - `command` — `SchemaCommand` enum value as a string (`create_asset_type`, `update_maintenance_record_type_field`, …). Emitted from the `schema_change_log.command` `TEXT` column verbatim; not re-validated against the enum on read (see *Why pass payload through* below — same argument).
  - `entity_id` — UUID string.
  - `payload` — the row's `JsonB` payload, passed through as-is.
  - `committed_at` — ISO-8601 UTC timestamp.
  - `actor_id` — `string | null`. Always `null` in M2; populated once auth lands (M5).
- `next_since` — the largest `seq` in the returned batch, or the request's `since` if `changes` is empty. Clients pass this back as the next `since` (semantics: "give me everything after the last row I saw").
- `has_more` — `true` iff `next_since < schema_version`. Tells the client whether to keep paging without re-querying.

### Cursor semantics

- `since` is **exclusive** (`seq > since`), matching ADR-011's prose and ADR-008's diff query (`seq > V_old`).
- `since=0` returns the full per-tenant history starting at the first row (`seq=1`).
- `since >= current_version` returns `{schema_version, changes: [], next_since: since, has_more: false}` — **not** an error. A caller who has caught up keeps polling cheaply.
- The `schema_version` returned in the response is the same value the snapshot endpoint would return at that instant; over a multi-page sweep the client sees a single point-in-time view *per request* but `schema_version` may advance between requests. The client should compare `next_since` to *each request's* `schema_version`, not cache an earlier one.

### Bounded batches

- `limit` defaults to a server-configured maximum and is capped to it. Out-of-range `limit` is a 400.
- The cap lives in `AppSettings.schema_changes_max_batch_size` (default `500`), tunable per deployment via `NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE`. The default is generous because schema-change-log rows are small (≤ a few KB each) and the typical catch-up is a few dozen rows; we want a single round-trip in the common case while still bounding pathological tenants.
- `has_more=true` is the signal to keep paging. There is no separate "you exceeded the cap" error — clients simply page.

### Errors

Rendered as `application/problem+json` per ADR-016 through the existing `ProblemDetailsPlugin`. No new `ErrorCode` values are introduced.

| Status | `type` URI leaf | Trigger |
|---|---|---|
| 400 | `invalid_payload_shape` | `since < 0`, `limit < 1`, `limit > max`, or a non-integer query value |
| 401 | `tenant_not_resolved` | No / invalid bearer token (upstream of the handler) |

`invalid_payload_shape` is reused rather than a new code: query-string validation is structurally identical to body validation (both are "the request couldn't be decoded against the expected shape"). Two paths land in the same code:

- **Type errors** (non-integer query value): caught by Litestar's `ValidationException`, already rendered as `invalid_payload_shape` via `make_litestar_validation_error_converter`.
- **Range errors** (`since < 0`, `limit < 1`, `limit > max`): raised by the handler as `PayloadShapeError(code=ErrorCode.INVALID_PAYLOAD_SHAPE, field=..., received=...)`. Same problem-details converter (`make_domain_error_converter`) handles them by inheritance.

The handler raises explicitly for ranges because the upper `limit` bound is settings-derived and not knowable at the route-decorator parse time — Litestar's `Parameter(ge=…, le=…)` constraints need literals.

## Consistency

Single transactional snapshot — `MAX(seq)` and the page of rows must reflect the same point-in-time. Concretely:

- One async session per request, one read transaction.
- Two queries inside it: `SELECT COALESCE(MAX(seq), 0) FROM schema_change_log` (the existing `SchemaChangeLogService.current_version()`), and `SELECT … FROM schema_change_log WHERE seq > :since ORDER BY seq LIMIT :limit`.
- SQLite's WAL gives us this snapshot for free as long as both reads share the session.

Order: read `MAX(seq)` **first**, then the page. Inverting the order would let a concurrent `POST /schema` commit a row between the two queries and produce a response where `next_since > schema_version`, which would mislead the client's `has_more` calculation. Inside one WAL snapshot the order doesn't matter, but we keep it stable for readability and because the snapshot guarantee depends on the connection-pool config (`StaticPool` in tests / `NullPool` in prod — both already enforce single-connection-per-request via Litestar's request-scoped session, but a defensive ordering costs us nothing).

## Cross-tenant isolation

The handler does not read or pass `tenant_id`. Both queries route through Layer 1 of `db._listeners`:

- The page query is an ORM `select(SchemaChangeLog)` ordered by `seq` → `state.all_mappers` is non-empty → `with_loader_criteria` injects `tenant_id = current_tenant_id.get()`.
- `current_version()` is a scalar aggregate → empty `state.all_mappers` → the listener's get-final-froms fallback path attaches the predicate directly on the Core `Select` (the same path the existing `current_version()` already relies on; we don't change anything here).

A new test in `tests/schema/test_cross_tenant_isolation.py` (or a parallel file — plan call) asserts that the catch-up endpoint returns only the active tenant's rows even when sibling tenants have committed interleaved schema changes with overlapping `seq` values.

## Why pass payload through as-is (not round-trip through `SchemaCommand` structs)

Round-tripping the `payload` through the corresponding `_payloads.py` struct on emission would catch drift between the persisted JSON and the current command-struct shape, but it's the wrong trade-off:

- **The payload was already validated** at POST time. The log is what we accepted; re-validating on read adds no safety to current data.
- **It couples read-history-reading to current command-struct shapes.** Renaming or removing a field on `_AssetTypeUpdatePayload` would break reads of older log rows that used the old shape. The whole point of the schema-as-data design (ADR-008) is that command vocabulary evolves without migrations; payload shape needs the same latitude.
- **It pulls the read endpoint into the discriminated-union machinery.** `_dispatch.py`'s `_HANDLERS` table is the command write path; entangling the read path with it makes "the command universe is one rg-able place" a less true statement.

If we want drift-detection later, the right place for it is an offline `ratchet`-style audit (read every row, attempt to decode, report mismatches) — not the hot read path.

## Code surface

- `novamoc/config.py` — add `AppSettings.schema_changes_max_batch_size: int` with `_int_env("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", 500)`. (`_int_env` is new — sibling of the existing `_float_env`; same `ValueError`-on-junk shape.)
- `novamoc/domain/schema/_read_payloads.py` — add three msgspec Structs:
  - `SchemaChangeView` — one row (`seq`, `command`, `entity_id`, `payload`, `committed_at`, `actor_id`).
  - `SchemaChangesResponse` — `schema_version`, `changes: tuple[SchemaChangeView, ...]`, `next_since`, `has_more`.
  - No new struct for the request — `since` and `limit` are query parameters bound declaratively on the handler signature.
- `novamoc/domain/schema/services/_change_log.py` — add `async def list_changes_after(self, *, since: int, limit: int) -> Sequence[SchemaChangeLog]:` that runs `SELECT … WHERE seq > :since ORDER BY seq LIMIT :limit` via the service's repository. (The existing `current_version()` is reused as-is.)
- `novamoc/domain/schema/controllers/_schema.py` — add a `@get("/changes")` handler on the existing `SchemaController`. It (1) reads `since` and `limit` as query parameters (both `Optional[int]`; the handler applies the default and bounds because the upper bound is settings-derived, not knowable at class-body parse time); (2) calls `current_version()` then `list_changes_after(since=since, limit=limit)` on the same request-scoped session; (3) maps rows to `SchemaChangeView`; (4) computes `next_since` and `has_more`; (5) returns the response.
  - Settings are injected via a `Provide(_provide_max_batch_size)` dependency reading `state.settings.app.schema_changes_max_batch_size` — same shape as `_provide_drift_limit_seconds` in `domain/events/controllers/_events.py`.
  - Bounds enforcement: when `since` or `limit` is out of range, the handler raises `PayloadShapeError(code=ErrorCode.INVALID_PAYLOAD_SHAPE, …)` with `field` and `received` extras, which renders through the existing problem-details converter.

No changes to `_dispatch.py`, `_handlers/`, `_commands.py`, `_bundle.py`, or `_payloads.py` — those are command-side only. No new database migrations (the table already exists with the right PK shape). No new error codes.

## Testing

Following repo conventions (real in-memory aiosqlite, no DB mocks):

E2E HTTP tests in `tests/schema/test_changes_endpoint_e2e.py`:

- 200 against an empty tenant → `{schema_version: 0, changes: [], next_since: 0, has_more: false}`.
- 200 after seeding N `POST /schema` commands and calling with `since=0` → all N rows, `next_since == N`, `has_more=false` (assuming N ≤ default limit).
- 200 with `since=k` (`0 < k < N`) → only rows `k+1..N`, `next_since == N`, `has_more=false`.
- 200 with `since >= current_version` → empty `changes`, `next_since == since`, `has_more=false`. Not an error.
- 200 with `?limit=2` against ≥ 3 rows → 2 rows, `has_more=true`, `next_since == seq of last row in batch`. A follow-up call with `since=next_since` returns the remainder and `has_more=false`.
- 400 for `since=-1`, `limit=0`, `limit > max`.
- 401 for missing / invalid `Authorization`.
- Row shape: each entry has all six fields including `actor_id: null`. `payload` is the original POST body (a small variety: `create_asset_type`'s `{"name": ...}`, `update_*`'s diff dict, an empty `{}` for `deactivate_*`).
- Tombstoning-then-resurrection appears as separate rows (not collapsed): `deactivate_asset_type` and `activate_asset_type` against the same `entity_id` both surface.
- Ordering: rows are ascending by `seq` regardless of physical insert order.

Service-level test in `tests/schema/test_change_log_service.py` (extend the existing file):

- `list_changes_after(since=k, limit=L)` returns rows ordered by `seq`, bounded to `L`, with `seq > k`.
- Tenant scoping: the cross-tenant isolation suite gets a parallel test that seeds `tA` and `tB` with overlapping `seq` ranges and verifies neither tenant's `list_changes_after` leaks the other's rows.

Handler-level tests are not added — this is a single read query, mirroring the precedent set by `GET /schema` whose design spec explicitly skipped that layer.

## OpenAPI

The new route adds `200` and `400` specs to `SchemaController`. The `200` response body is `SchemaChangesResponse`. The `400` and `401` responses reuse the existing `ProblemDetails` `ResponseSpec` already wired on the controller. The OpenAPI doc continues to live at `/openapi`.

## Notable non-changes

- `POST /schema` is untouched. So is `GET /schema`.
- No new tables, columns, or indexes. The `schema_change_log` composite PK `(tenant_id, seq)` already serves the `WHERE tenant_id = ? AND seq > ? ORDER BY seq LIMIT ?` query optimally.
- No new `ErrorCode` values.
- No new ADR — the protocol shape was decided in ADR-008/ADR-009 already; this is the implementation.

## Open questions deferred to a future iteration

- **Long-poll / streaming variant**: clients currently poll; once WebSocket transport (ADR-013) lands, the `schema_changed` push will obviate most polling. Not needed in M2.
- **Drift audit**: an offline tool that re-parses every `payload` through current `_payloads.py` structs and reports mismatches. Useful diagnostic, but not on the hot path; defer until we have evidence of drift.
