# Schema Read Endpoint Design

## Status

Draft

## Purpose & scope

Add `GET /schema/{tenant_id}` — the read counterpart to the existing `POST /schema` command endpoint (ADR-008). Returns the full per-tenant schema projection (asset types, asset type fields, maintenance record types, maintenance record type fields) plus the tenant's current `schema_version`, in a single response.

Out of scope:

- Any client-side use of the response (cache shape, OPFS, persistence, ETag tracking) — this spec covers only the HTTP contract and server implementation.
- The schema-change-log diff endpoint used by the ADR-009 upgrade flow — different operation, different shape, separate spec.
- Authentication and a real tenant registry — see *Tenant resolution* below.

## HTTP contract

### Route

`GET /schema/{tenant_id}`, mounted on the existing `SchemaController` (which already owns `/schema`).

### Tenant resolution

A hardcoded `KNOWN_TENANT_IDS: frozenset[str]` lives in `novamoc/config.py` and starts as a single dev tenant. The handler checks `tenant_id in KNOWN_TENANT_IDS` first; an unknown tenant yields **404 `tenant_not_found`** before any DB work.

This is a deliberate stub. The real tenant registry will land in a future ADR/spec along with authentication; at that point `POST /schema` (which today accepts any `tenant_id` it sees in the request body) is aligned with the same registry. **Tech debt is recorded by this asymmetry**: the read side enforces the registry, the write side does not, until the registry lands properly. Tracked in [#19](https://github.com/shoriminimoe/novamoc/issues/19).

### Success response — 200 OK

```json
{
  "schema_version": 47,
  "asset_types": [
    {
      "id": "8c1d…",
      "name": "Truck",
      "active": true,
      "fields": [
        {
          "id": "f0a1…",
          "name": "VIN",
          "data_type": "text",
          "validation": null,
          "active": true
        }
      ]
    }
  ],
  "maintenance_record_types": [
    {
      "id": "…",
      "name": "Oil change",
      "active": true,
      "fields": [
        { "id": "…", "name": "mileage", "data_type": "integer",
          "validation": {"min": 0}, "active": true }
      ]
    }
  ]
}
```

Headers:

```
ETag: "47"
Content-Type: application/json
```

Notes on the shape:

- `schema_version` = `MAX(seq) FROM schema_change_log WHERE tenant_id = ?`, or `0` for an empty tenant.
- Both type rows and field rows always carry `active`. Tombstoned rows (`active = false`) are included; ADR-009 establishes that data events targeting `deactivate_*`-d fields are still valid, so any client validating events against the cached schema needs to see them. Filtering for UI display is a read-time concern for the consumer.
- Fields are nested under their parent type. The wire shape mirrors the conceptual shape (a type owns its fields), not the storage layout (four flat tables). Consumers that want a flat view can produce one trivially; consumers that want a nested view would otherwise have to invert a flat response.
- Audit columns (`created_at`, `updated_at`) on the projection rows are deliberately omitted from the wire shape. The schema endpoint exposes current state; audit history is the schema-change-log diff endpoint's job.
- IDs are UUID strings. `data_type` is the `FieldDataType` `StrEnum` value (a string). `validation` is the projection's JSON column passed through verbatim (`null` when unset).

### Conditional GET — 304 Not Modified

The `schema_version` integer uniquely identifies the projection state, so it doubles as the ETag value:

```
GET /schema/{tenant_id}
If-None-Match: "47"
→ 304 Not Modified
ETag: "47"
```

Behaviour:

- Every response (200 *and* 304) carries `ETag: "<schema_version>"` as a quoted string. Empty tenants get `ETag: "0"`.
- A request whose `If-None-Match` matches the current `schema_version` returns 304 with the ETag header and no body.
- Any version mismatch (or no `If-None-Match` header) returns the full 200 body.
- The conditional check happens *after* the registry check — an unknown tenant always returns 404 regardless of `If-None-Match`.

### Error responses

Rendered as `application/problem+json` per ADR-016 through the existing `ProblemDetailsPlugin` registered in `novamoc.asgi.create_app`.

| Status | `type` URI leaf  | Trigger                                | Extension members |
|--------|------------------|----------------------------------------|-------------------|
| 404    | `tenant_not_found` | `tenant_id` not in `KNOWN_TENANT_IDS` | `tenant_id`       |

Implementation:

- `ErrorCode.TENANT_NOT_FOUND = "tenant_not_found"` is added to the `ErrorCode` enum in `domain/schema/_errors.py`, with a corresponding entry in `_DEFAULT_MESSAGES`.
- The base class `SchemaCommandError` is renamed to `SchemaError` (its name no longer fits now that read-side errors share it). The four existing subclasses (`PayloadShapeError`, `ConflictError`, `EntityNotFoundError`, plus the new `TenantNotFoundError`) all inherit from it; the mapper function is renamed in lockstep (`schema_command_error_to_problem_details` → `schema_error_to_problem_details`) and re-registered in `asgi.create_app`.
- `_problem_details.py` gains entries in `_TITLES` (e.g., `"Tenant not found"`) and `_STATUS_CODES` (`404`) for the new code. The existing mapper picks up `TenantNotFoundError` by inheritance — no new mapper entry is needed.
- The `tenant_id` extension member is passed via `**extras` on the exception, the same way `name=...` and `field=...` ride out today.

## Consistency

The full response — `schema_version` plus all four projections — must reflect a single transactional snapshot. Concretely:

- One async session per request, one read transaction.
- All five queries inside that transaction: four projection `SELECT`s and `SELECT MAX(seq) FROM schema_change_log WHERE tenant_id = ?`.

Without a snapshot, a `POST /schema` landing between queries can produce a response whose `schema_version` doesn't match the projection state — for example, a `schema_version` of 47 reflecting a row the projection query missed, or vice versa. SQLite's WAL mode gives a single read snapshot for the duration of the transaction at no extra cost; the only requirement is that the controller hold one session across all five queries.

This is the same idea ADR-015 enforces across initial-sync batches with `schema_version` re-checks; here it's free because the entire response is one batch.

## Pagination

None. The schema for a tenant is bounded — typically a handful of types and dozens of fields, a few KB at most on the wire. Pagination would either need its own consistency story (re-checking `schema_version` across pages, ADR-015 style) or would silently lose snapshot consistency. The single-batch design avoids both costs.

## Empty tenant

A tenant in `KNOWN_TENANT_IDS` with no schema rows returns:

```json
{
  "schema_version": 0,
  "asset_types": [],
  "maintenance_record_types": []
}
```

with `ETag: "0"`. Schema is data; "no rows yet" is a valid state, indistinguishable from "every row was `delete_*`-d." Returning 200 with an empty projection lets a client begin issuing `POST /schema` commands without first having to handle a "not yet bootstrapped" branch.

## Code surface

- `novamoc/config.py` — add `KNOWN_TENANT_IDS: frozenset[str]` initialized to a single dev tenant constant.
- `novamoc/domain/schema/_payloads.py` (or a sibling `_read_payloads.py` if the file is getting busy — a plan-level decision) — new `msgspec.Struct`s: `SchemaSnapshotResponse`, `AssetTypeView` (with nested `fields: list[AssetTypeFieldView]`), `AssetTypeFieldView`, and the maintenance-record analogues. These are response-only structs; they do not participate in the `SchemaRequest` discriminated union.
- `novamoc/domain/schema/_errors.py` — rename `SchemaCommandError` → `SchemaError`; add `ErrorCode.TENANT_NOT_FOUND` (and matching `_DEFAULT_MESSAGES` entry) and a `TenantNotFoundError(SchemaError)` subclass.
- `novamoc/api/_problem_details.py` — add `TENANT_NOT_FOUND` entries to `_TITLES` and `_STATUS_CODES`; rename the mapper function to match the renamed base; update its `asgi.create_app` registration accordingly. No new mapper function — the existing one handles all `SchemaError` subclasses by inheritance.
- `novamoc/domain/schema/controllers/_schema.py` — add a `@get("/{tenant_id:str}")` handler on `SchemaController`. It (1) validates `tenant_id` against `KNOWN_TENANT_IDS`, raising `TenantNotFoundError` on miss; (2) opens (or uses the request-scoped) read session; (3) queries the four projection services and `MAX(seq)` from `SchemaChangeLogService`; (4) assembles the nested response and sets the `ETag` header; (5) honours `If-None-Match` by comparing against the computed `schema_version` and returning 304 if matched.

No changes to `_dispatch.py`, `_handlers/`, `_commands.py`, or `_bundle.py` — those are command-side only. The four service classes (`AssetTypeService`, `AssetTypeFieldService`, `MaintenanceRecordTypeService`, `MaintenanceRecordTypeFieldService`) are reused as-is for the read; `SchemaChangeLogService` gets a small `current_version(tenant_id)` method (or the controller queries `MAX(seq)` directly via the session — plan call).

## Testing

Following repo conventions (real in-memory aiosqlite, no DB mocks):

E2E tests in `tests/schema/test_read_endpoint_e2e.py`:

- 200 against the seeded dev tenant with no schema rows → empty projection, `schema_version: 0`, `ETag: "0"`.
- 200 after seeding a few `POST /schema` commands → full nested shape, correct `schema_version` matching the latest committed `seq`, matching ETag.
- 304 round-trip: `If-None-Match` matches current version → 304 with ETag header and no body.
- 304 stale: `If-None-Match: "0"` after writes → 200 with full body and updated ETag.
- 404 against an unknown `tenant_id` → problem-details body with `type` URI leaf `tenant_not_found` and a `tenant_id` extension member.
- Tombstoned rows: a `deactivate_*`-d type and a `deactivate_*`-d field both appear in the response with `active: false`, alongside their active siblings.

Handler-level tests are not added — this is a single read query, not a verb table, so the E2E tests cover the meaningful behaviour without an intermediate seam.

`tests/conftest.py` already provides the `client`, `app`, `services`, and shared-cache in-memory database needed by these tests; no new fixtures are required beyond a small helper to seed schema rows.

## OpenAPI

The new route adds 200, 304, and 404 specs to `SchemaController`. The 200 response body is `SchemaSnapshotResponse`. The 304 response carries no body (just headers). The 404 response uses the existing `ProblemDetails` ResponseSpec already wired on the controller. The OpenAPI doc continues to live at `/openapi` (per `asgi.create_app`).

## Notable non-changes

- `POST /schema`'s controller method, dispatch table, handlers, request payloads, response payload, and services are untouched. The read endpoint shares only the controller mount, the model classes, and the problem-details rendering.
- `schema_change_log` is read for `MAX(seq)` only. Streaming the change log itself (for the ADR-009 upgrade-diff narrative) is a separate endpoint with a separate response shape, outside this spec's scope.
- No new database migrations. No new tables, columns, or indexes. The `schema_change_log` composite PK `(tenant_id, seq)` already supports the `MAX(seq) WHERE tenant_id = ?` lookup efficiently via the implicit PK index.

## Recorded tech debt

- **Single hardcoded tenant in `KNOWN_TENANT_IDS`** — tracked in [#19](https://github.com/shoriminimoe/novamoc/issues/19). Replaced by a real tenant registry once authentication and tenant management land. At that point `POST /schema` is gated by the same registry so the read/write asymmetry disappears.
