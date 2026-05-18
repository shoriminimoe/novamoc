# Design: `GET /sync/initial` bulk projection transfer

## Status

Drafted 2026-05-18. Closes M2.3 (issue #33). The HTTP half of ADR-015; flips
the ADR to Accepted on ship.

## Problem

A fresh client (new device, cleared local storage) needs to populate its
local SQLite with the active tenant's data-projection state before it can
go live. ADR-015 commits to **full** initial sync: ship the projections
(not the event log) plus a cursor the client uses to start incremental
sync (M2.4 catch-up, M3 WS). This spec is that endpoint.

Concretely, the client needs:

1. Current state of `assets`, `maintenance_records`, `asset_field_values`,
   `maintenance_record_field_values` for the tenant — including tombstones,
   with `*_field_values` HLCs preserved so subsequent folds against incoming
   events are correct (ADR-007).
2. The `schema_version` that state was projected under (ADR-009 / ADR-015
   §"Consistency").
3. The `event_log.seq` cursor where catch-up should begin (ADR-011) — this
   must be captured **before** the projection reads start so events that
   fire mid-transfer are not silently skipped (see §"Why `start_seq`
   on the first request" below).

Two things have to be true that the current system does not provide:

1. **An HTTP endpoint** that returns the projection state in bounded
   batches, with a continuation token that survives across requests.
2. **A wire envelope** that distinguishes the four projection tables (their
   row shapes differ) and carries the cross-batch consistency signals
   (`schema_version`, `cursor`, terminal `event_log_cursor`).

## Goals

1. Add `GET /sync/initial` that streams the active tenant's data
   projection in fixed-table-order batches, capped by a
   `results_per_page` query parameter, with an opaque continuation
   `cursor`.
2. Define `InitialSyncBatch` (custom msgspec struct) with a `table`-tagged
   discriminated union body so each batch is a homogeneous list of one
   table's rows.
3. Capture the per-tenant `event_log.seq` ceiling on the first request
   and thread it through every subsequent cursor; emit it as
   `event_log_cursor` on the terminal batch only.
4. Match the existing endpoint conventions: tenant scoping via
   `TenantContextMiddleware` + Layer 1 listener, no tenant in URL or
   body, `application/problem+json` on errors per ADR-016,
   handler-level + E2E tests against a real in-memory SQLite (no
   mocks).
5. Register `SyncController` in `asgi.create_app` alongside
   `SchemaController` and `EventsController`.

## Non-goals

- **Schema transfer.** Clients already fetch the full schema snapshot
  via `GET /schema` (M2.1). Initial sync is just the *data* projections.
  ADR-015 §"Flow" describes the schema fetch as a separate step.
- **`*Properties` on the wire.** Per ADR-015 §"Derived entity JSON",
  the default is *compute on client from field values*. We omit
  `assets.properties` / `maintenance_records.properties` and
  `assets.name` (which mirrors `col:name`) from the wire — the client
  reconstructs them by folding the per-field rows. Reintroduce server-
  side if profiling on a large tenant demands it; an optimisation, not
  a correctness requirement.
- **WebSocket variant.** Initial sync is HTTP-only by ADR-013's
  decomposition (`/sync` is bulk, WS is incremental). M3 reads the
  cursor this endpoint returns; it doesn't replicate the bulk path.
- **Resume across schema-version change.** If `schema_version` advances
  mid-transfer the client restarts (ADR-015 §"Consequences"). The
  endpoint emits the current `schema_version` on each batch so the
  client can detect the change; it does not enforce restart server-side.
- **Cursor signing / tamper-detection.** The cursor is base64 JSON with
  no signature. A client that tampers with `start_seq` only hurts
  itself (duplicate work for lower values, missed events for higher).
  Out of scope for v1; revisit if cursors leave a single client/server
  trust boundary.
- **Hard delete / projection compaction.** Tombstones (`deleted=true`)
  ship as part of the projection. ADR-002 / ADR-019.
- **Schema-version ETag / 304.** Bulk transfer is page-shaped, not
  resource-shaped. Clients drive freshness via the `cursor` field.

## Architecture

### Module layout

```
src/py/novamoc/
├── config.py                          # MODIFIED: INITIAL_SYNC_* constants
├── asgi.py                            # MODIFIED: register SyncController
└── domain/sync/                       # NEW package
    ├── __init__.py
    ├── _cursor.py                     # NEW: opaque cursor encode/decode
    ├── _pagination.py                 # NEW: InitialSyncPaginator
    ├── _payloads.py                   # NEW: InitialSyncBatch + body union
    ├── services.py                    # NEW: 4 projection-table services
    └── controllers/
        ├── __init__.py
        └── _sync.py                   # NEW: SyncController
tests/sync/                            # NEW
├── __init__.py
├── test_cursor.py                     # NEW: encode/decode + tamper
├── test_pagination.py                 # NEW: paginator unit tests
├── test_endpoint_sync_initial.py      # NEW: E2E
└── test_sync_cross_tenant_isolation.py# NEW
```

No changes to `db/models/` — the four projection tables already exist and
carry every column we need (entity tables in M1.7, `*_field_values` in
M1.6).

### HTTP contract

#### Route

`GET /sync/initial`, mounted on a new `SyncController` (path `/sync`).
The endpoint is named with the `/initial` suffix so a future incremental
companion under `/sync` (e.g. M2.4's `GET /events` could be re-homed if
ever needed) doesn't collide.

Query parameters:

| Name              | Type          | Default | Bounds                 | Meaning                                                                  |
|-------------------|---------------|---------|------------------------|--------------------------------------------------------------------------|
| `cursor`          | `str \| null` | `null`  | opaque                 | `null` → start of transfer. Otherwise an opaque token from a prior batch. |
| `results_per_page`| `int`         | `1000`  | `1 ≤ n ≤ 5000`         | Cap on the number of rows in `body.items`.                               |

Defaults and the upper bound come from `config.INITIAL_SYNC_*` constants
(see §"Settings" below).

#### Success response — 200 OK

```jsonc
{
  "schema_version": 12,
  "cursor": "eyJzdGFydF9zZXEiOjE3LCJ0YWJsZSI6ImFzc2V0X2ZpZWxkX3ZhbHVlcyIsImxhc3RfaWQiOiI3ZmU2…",
  "event_log_cursor": null,
  "body": {
    "table": "assets",
    "items": [
      {
        "id": "8c1d…",
        "type_id": "f0a1…",
        "deleted": false,
        "row_state_hlc": "0001700000000000-00000-abc",
        "created_at": "2026-05-17T09:14:22.193Z",
        "updated_at": "2026-05-17T09:14:23.041Z"
      }
    ]
  }
}
```

Terminal batch (transfer complete):

```jsonc
{
  "schema_version": 12,
  "cursor": null,
  "event_log_cursor": 17,
  "body": {
    "table": "maintenance_record_field_values",
    "items": [ /* … final rows, possibly empty … */ ]
  }
}
```

##### Field-by-field

- `schema_version` — server's current `schema_version` *at request time*
  (`SchemaChangeLogService.current_version()`). Advances are observable
  across batches; the client compares and restarts if it changes
  (ADR-015 §"Consistency"). Per-batch internal consistency is provided
  by the single-request SQLite WAL snapshot — the `current_version` read
  and the projection read share one transaction.
- `cursor` — opaque continuation. `null` ⇒ the transfer is complete.
  Non-null ⇒ pass back as `?cursor=<value>` on the next request. See
  §"Cursor encoding" for the internal shape.
- `event_log_cursor` — `int` only on the terminal batch (when `cursor`
  is `null`); `null` on every intermediate batch. Captured on the first
  request and threaded through cursors; equals `MAX(event_log.seq)`
  observed when the client's transfer began. The client passes this as
  `?cursor=<event_log_cursor>` to `GET /events` (M2.4) and as the WS
  hello cursor (M3).
- `body.table` — the projection table these `items` came from. One of
  `assets`, `asset_field_values`, `maintenance_records`,
  `maintenance_record_field_values`. msgspec discriminator (`tag_field
  = "table"`).
- `body.items` — homogeneous list of rows. Shape varies by `table` (see
  §"Row views").

##### Row views

Defined in `domain/sync/_payloads.py`:

```python
class AssetView(msgspec.Struct, forbid_unknown_fields=True):
    id: UUID
    type_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class AssetFieldValueView(msgspec.Struct, forbid_unknown_fields=True):
    asset_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str


class MaintenanceRecordView(msgspec.Struct, forbid_unknown_fields=True):
    id: UUID
    type_id: UUID
    asset_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class MaintenanceRecordFieldValueView(msgspec.Struct, forbid_unknown_fields=True):
    maintenance_record_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str
```

What's intentionally **not** on the wire:

- `assets.name` / `maintenance_records.name` — these mirror `col:name` in
  `*_field_values`. The client reconstructs them by folding the
  field-value rows it receives. ADR-005 / ADR-012 / ADR-019.
- `assets.properties` / `maintenance_records.properties` — derivable
  the same way. ADR-015 §"Derived entity JSON" defaults this off.
- `tenant_id` — pre-resolved from the request; the client doesn't need
  it echoed back.

Tombstones (`deleted=true` rows) **are** included; the `deleted` boolean
rides on `AssetView` / `MaintenanceRecordView`. Schema tombstones
(deactivated types/fields) live in the schema snapshot, not here.

##### Discriminated body

```python
class _SyncBody(msgspec.Struct, tag_field="table"):
    """Discriminator base for ``InitialSyncBody``.

    Subclasses set ``tag`` to the table name. msgspec publishes the union
    as ``oneOf`` discriminated on ``table`` in the OpenAPI schema.
    """


class AssetsBatchBody(_SyncBody, tag="assets"):
    items: tuple[AssetView, ...]


class AssetFieldValuesBatchBody(_SyncBody, tag="asset_field_values"):
    items: tuple[AssetFieldValueView, ...]


class MaintenanceRecordsBatchBody(_SyncBody, tag="maintenance_records"):
    items: tuple[MaintenanceRecordView, ...]


class MaintenanceRecordFieldValuesBatchBody(
    _SyncBody, tag="maintenance_record_field_values"
):
    items: tuple[MaintenanceRecordFieldValueView, ...]


InitialSyncBody = (
    AssetsBatchBody
    | AssetFieldValuesBatchBody
    | MaintenanceRecordsBatchBody
    | MaintenanceRecordFieldValuesBatchBody
)


class InitialSyncBatch(msgspec.Struct, forbid_unknown_fields=True):
    schema_version: int
    cursor: str | None
    event_log_cursor: int | None
    body: InitialSyncBody
```

#### Errors

Rendered as `application/problem+json` per ADR-016 through the existing
`ProblemDetailsPlugin`. **No new** `ErrorCode` values.

| Status | `type` URI leaf            | Trigger                                                       |
|--------|----------------------------|---------------------------------------------------------------|
| 400    | `invalid_payload_shape`    | `cursor` malformed (bad base64 / not JSON / missing fields).  |
| 400    | (Litestar ValidationException) | `results_per_page` < 1 or > `INITIAL_SYNC_MAX_BATCH_SIZE`. |
| 401    | (`AuthenticationMiddleware`) | Missing / invalid bearer.                                    |

Tampered cursors that decode successfully but reference a `table` that
isn't one of the four known names also surface as
`invalid_payload_shape`. A cursor whose `start_seq` is internally
consistent but doesn't match any seq the server has issued is
**accepted** — the client is allowed to pick any starting seq; that's
the trust model (see §"Cursor encoding").

### Cursor encoding

`_cursor.py` exposes two pure functions and one error type:

```python
@dataclass(frozen=True, slots=True)
class CursorState:
    """The state a cursor encodes between requests.

    Attributes:
        start_seq: The ``MAX(event_log.seq)`` observed on the first
            request, threaded through every cursor for the duration of
            the transfer. Returned to the client as ``event_log_cursor``
            on the terminal batch.
        table: The next projection table to read from. One of the four
            ``InitialSyncTable`` values.
        last_id: The encoded last-seen primary key in ``table``, or
            ``None`` to start at the beginning of ``table``. For entity
            tables this is a single UUID string; for ``*_field_values``
            it is ``"<entity_uuid>:<field_id>"``.
    """

    start_seq: int
    table: InitialSyncTable
    last_id: str | None


def encode_cursor(state: CursorState) -> str:
    """URL-safe base64 of compact JSON. Trailing ``=`` padding stripped."""


def decode_cursor(token: str) -> CursorState:
    """Inverse of :func:`encode_cursor`.

    Raises:
        PayloadShapeError(INVALID_PAYLOAD_SHAPE): token isn't valid
            base64-JSON, or the decoded object is missing required
            fields, has the wrong field types, or names a ``table``
            that isn't one of the four known projection tables.
    """
```

`InitialSyncTable` is a `StrEnum` with values
`assets`, `asset_field_values`, `maintenance_records`,
`maintenance_record_field_values` — the same strings that appear as
discriminator tags on the body union. Single source of truth.

**Format choice — URL-safe base64 of JSON**, not a signed token. The
threat model is: a malicious client can decode and modify the cursor.
If they raise `start_seq`, they miss events on M2.4 catch-up (their
loss). If they lower it, they re-fold events they already had (their
loss). The server reads `last_id` as a `seq > last_id` range filter,
so an invalid `last_id` returns extra rows or misses some — also a
self-inflicted wound. None of these cross the tenant boundary because
Layer 1 still scopes every read. We can add HMAC signing in a future
iteration if a different deployment model warrants it.

**Why not Litestar's `CursorPagination[int, T]`** — the items differ in
shape per batch (four row views), and the cursor needs to carry
`start_seq` in addition to a per-table offset. Litestar's
`CursorPagination` is parametrised by `(CursorType, ItemType)` with a
single homogeneous item list, which is the wrong shape for this
endpoint. We define our own envelope.

### The paginator

`_pagination.py` implements the four-table walk in a single class.
Patterned on `EventLogCursorPaginator` (M2.4) but custom-coded because
of the table-walking and the start-seq capture.

```python
class InitialSyncPaginator:
    """Walks the four projection tables in fixed order.

    The four projection-table services and the change-log service are
    injected. ``__call__(cursor, results_per_page)`` is the only
    public entry point — it captures ``start_seq`` on the first call
    (when ``cursor is None``), pages within the current table, advances
    to the next non-empty table when the current one runs out, and
    emits the terminal batch with ``event_log_cursor=start_seq`` when
    every table is exhausted.

    Tenant scoping is structural: every ``.list(...)`` call hits Layer
    1 of the tenant-scoping listeners and is filtered to the active
    tenant. The paginator carries no tenant predicate of its own.
    """

    def __init__(
        self,
        change_log_service: SchemaChangeLogService,
        event_log_service: EventLogService,
        asset_service: AssetService,
        asset_field_value_service: AssetFieldValueService,
        maintenance_record_service: MaintenanceRecordService,
        maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
    ) -> None: ...

    async def __call__(
        self, cursor: str | None, results_per_page: int
    ) -> InitialSyncBatch: ...
```

##### Algorithm

```
def serve_batch(cursor, n):
    if cursor is None:
        start_seq = MAX(event_log.seq) for tenant  # 0 if empty
        position  = (table=assets, last_id=None)
    else:
        state = decode(cursor)
        start_seq, position = state.start_seq, (state.table, state.last_id)

    schema_version = current_version()

    for table in TABLES_FROM(position.table):
        last_id = position.last_id if table == position.table else None
        rows = read_page(table, last_id, n + 1)
        has_more_in_table = len(rows) > n
        rows = rows[:n]
        if rows or table is TABLES[-1]:
            if has_more_in_table:
                next_state = CursorState(start_seq, table, last_id_of(rows[-1]))
                next_cursor = encode(next_state)
                event_log_cursor = None
            elif table is TABLES[-1]:
                next_cursor = None
                event_log_cursor = start_seq
            else:
                next_state = CursorState(start_seq, table_after(table), None)
                next_cursor = encode(next_state)
                event_log_cursor = None
            return Batch(schema_version, next_cursor, event_log_cursor,
                          body=body_for(table, rows))
    # unreachable: the last-table branch above always returns
```

This collapses empty intermediate tables: when `read_page` returns no
rows and we're not on the last table, we loop and try the next one in
the same request. An empty tenant returns one batch (`table=assets`,
`items=()`, `cursor=null`, `event_log_cursor=0`) — a single round-trip.

`TABLES` is the fixed tuple `(assets, asset_field_values,
maintenance_records, maintenance_record_field_values)`. The order is a
contract — `maintenance_record_field_values` is always last because its
`event_log_cursor` ride is what signals "done."

##### `read_page` and ordering

Each table read uses advanced-alchemy filters to enforce stable
ordering and the `last_id` predicate:

| Table                                | `ORDER BY`               | `last_id` predicate                                                                |
|--------------------------------------|--------------------------|-------------------------------------------------------------------------------------|
| `assets`                             | `id`                     | `id > UUID(last_id)`                                                                |
| `maintenance_records`                | `id`                     | `id > UUID(last_id)`                                                                |
| `asset_field_values`                 | `asset_id, field_id`     | `(asset_id, field_id) > (UUID(eid), fid)` — see §"Tuple comparison" below |
| `maintenance_record_field_values`    | `maintenance_record_id, field_id` | `(maintenance_record_id, field_id) > (UUID(eid), fid)`                  |

Stable ordering is mandatory for resumption: `(table, last_id)` only
makes sense if successive reads at the same `last_id` produce a
consistent prefix.

###### Tuple comparison

SQLite supports row-value comparison (`(a, b) > (c, d)` ⇔ `a > c OR (a
= c AND b > d)`), and SQLAlchemy emits this via the `tuple_()`
construct. The `_field_values` queries can use it directly:

```python
from sqlalchemy import tuple_

await asset_field_value_service.list(
    tuple_(AssetFieldValue.asset_id, AssetFieldValue.field_id)
        > tuple_(decoded_entity_uuid, decoded_field_id),
    OrderBy(field_name="asset_id"),
    OrderBy(field_name="field_id"),
    LimitOffset(limit=results_per_page + 1, offset=0),
)
```

Falling back to a `(asset_id > ?) OR (asset_id = ? AND field_id > ?)`
expansion is a one-line change if row-value comparison turns out to
misbehave at the advanced-alchemy layer.

### Services

`_services.py` exposes four read-only advanced-alchemy services. They
follow the exact same shape as `EventLogService`:

```python
class AssetService(service.SQLAlchemyAsyncRepositoryService[Asset]):
    class Repo(repository.SQLAlchemyAsyncRepository[Asset]):
        model_type = Asset
    repository_type = Repo


class AssetFieldValueService(
    service.SQLAlchemyAsyncRepositoryService[AssetFieldValue]
):
    class Repo(repository.SQLAlchemyAsyncRepository[AssetFieldValue]):
        model_type = AssetFieldValue
    repository_type = Repo


# … MaintenanceRecordService, MaintenanceRecordFieldValueService …
```

These are sync-domain reads only; the write path (the events fold)
continues to use the raw-SQLAlchemy helpers in `domain/events/_fold.py`
/ `_projection.py` / `_row_state.py`. There is no risk of overlap.

### Controller

```python
class SyncController(Controller):
    path = "/sync"
    tags = ("sync",)
    dependencies = (
        {"paginator": Provide(_provide_initial_sync_paginator)}
        | providers.create_service_dependencies(SchemaChangeLogService,
                                                "schema_change_log_service")
        | providers.create_service_dependencies(EventLogService,
                                                "event_log_service")
        | providers.create_service_dependencies(AssetService,
                                                "asset_service")
        | providers.create_service_dependencies(AssetFieldValueService,
                                                "asset_field_value_service")
        | providers.create_service_dependencies(MaintenanceRecordService,
                                                "maintenance_record_service")
        | providers.create_service_dependencies(
              MaintenanceRecordFieldValueService,
              "maintenance_record_field_value_service")
    )

    @get(
        "/initial",
        responses={
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid cursor or batch size",
                media_type="application/problem+json",
            ),
        },
    )
    async def initial(
        self,
        paginator: InitialSyncPaginator,
        cursor: str | None = None,
        results_per_page: Annotated[
            int, Parameter(ge=1, le=INITIAL_SYNC_MAX_BATCH_SIZE)
        ] = INITIAL_SYNC_DEFAULT_BATCH_SIZE,
    ) -> InitialSyncBatch:
        return await paginator(cursor=cursor, results_per_page=results_per_page)
```

The controller is thin by design: bound checking lives in the Litestar
`Parameter(...)` annotation (`ValidationException` → 400 problem-details
through the existing plugin), cursor decoding lives in the paginator
(`PayloadShapeError` → 400 problem-details through the existing
plugin), tenant scoping is structural. The handler does no manual error
mapping.

### Settings

Two new module-level constants in `config.py`, next to the existing
`EVENT_CATCHUP_*` pair:

```python
INITIAL_SYNC_DEFAULT_BATCH_SIZE = 1000
INITIAL_SYNC_MAX_BATCH_SIZE = 5000
```

Imported directly by the controller for use in the `Parameter(...)`
literal bounds. No env-var override surface for v1 — these are
defensible round numbers, not tuned values, and changing them is a code
edit, not a deploy-time knob. ADR-015 §"Batch shape" recommends "a
starting target of a few thousand rows per batch"; 1000 default with
5000 ceiling lands inside that band and matches the upper bound of the
events catch-up endpoint for operational consistency.

### `asgi.create_app` wiring

One additional import and one extra entry in `route_handlers`:

```python
from novamoc.domain.sync.controllers import SyncController
…
return Litestar(
    route_handlers=[SchemaController, EventsController, SyncController,
                    problem_docs_router],
    …
)
```

### Why `start_seq` on the first request

A correctness subtlety the issue alludes to but the spec must pin down.
Three options exist for *when* to compute the per-tenant
`event_log.seq` ceiling:

1. **End of transfer.** Compute `MAX(event_log.seq)` on the terminal
   batch.
2. **Start of transfer.** Compute on the first request, thread through
   the cursor, emit on the terminal batch.
3. **Per batch.** Recompute on each batch; client takes the value from
   the terminal batch.

Option (1) has a silent-skip bug. Sequence: batch 1 reads `assets`
including asset X at state S1. An event accepted between batches
updates X to S2. Batch 4 (the terminal one) reads
`MAX(event_log.seq)` *after* that new event committed. The client now
has X at S1 in its local projection, and starts catch-up *past* the
event that would have updated it to S2. X is stuck at S1 until the
next write to it. **Unacceptable.**

Option (3) has the same bug as (1) for any cursor value the terminal
batch ends up emitting — it's still observed after the projection
reads.

Option (2) — capture *before* any projection rows are read — places
`start_seq` strictly **at or below** the seq of every event whose
write the projection observed. Any event with `seq > start_seq` is
absent from the projection the client receives, and the client will
fetch it via M2.4 catch-up and fold it correctly via per-field LWW
(ADR-007). Any event with `seq ≤ start_seq` is already reflected in
*either* the batch the client has already received (an earlier seq's
effect persisted to a projection row) *or* the batch the client is
about to receive (the same effect, same row, same value). Either way
the eventual state after M2.4 is correct.

Implementation: the paginator computes `start_seq` exactly when
`cursor is None` (the first request), encodes it into the cursor it
returns, and on subsequent requests reads it back out. No
per-batch recomputation.

### What stays unchanged

- The events endpoint (`POST /events`, `GET /events`) — initial sync
  is read-only against projections and does not interact with the
  event log writers.
- The schema endpoint (`GET /schema`, `POST /schema`, `GET
  /schema/changes`) — clients fetch schema separately.
- The fold writers (`_fold.py`, `_projection.py`, `_row_state.py`) —
  this endpoint only reads.
- The tenant-scoping listeners — Layer 1 scopes every read here for
  free. The new services compose `TenantScopedMixin` via their
  `model_type`s; the listener triggers off column presence.
- `RecordedEvent` / `EventEnvelope` and the `event_log` schema — the
  `event_log` is only read for its `MAX(seq)` per tenant in this
  endpoint, and that read goes through the existing `EventLogService`.

## Tests

All tests use the project's standard fixtures: real in-memory aiosqlite,
no mocks. New tests live under `tests/sync/`.

### `test_cursor.py`

Pure unit tests for `encode_cursor` / `decode_cursor`:

- Roundtrip for every `InitialSyncTable` variant, with `last_id` both
  `None` and populated (entity UUID for entity tables, `"uuid:field_id"`
  for field-value tables).
- Tamper rejection: garbage base64 → `PayloadShapeError`; valid base64
  decoding to non-JSON → `PayloadShapeError`; JSON missing required
  fields → `PayloadShapeError`; JSON naming an unknown table →
  `PayloadShapeError`.
- Trailing `=` padding handling (stripped on encode, accepted with or
  without on decode).

### `test_pagination.py`

`InitialSyncPaginator` constructed against the `services`-style fixtures
(no HTTP):

- **Empty tenant.** No assets, no records, no field values, no events
  ⇒ first call returns `cursor=None`, `event_log_cursor=0`,
  `body=AssetsBatchBody(items=())`.
- **Single non-empty table, fits one page.** Seed N assets only.
  First call: `body.items` has N entries, `cursor=None`,
  `event_log_cursor=0` (no events yet from event_log).
- **Single non-empty table, multiple pages.** Seed N assets with
  `results_per_page < N`. Iterate; assert items are returned in `id`
  order, no duplicates, no gaps, last response has `cursor=None`.
- **Cursor walk across all four tables.** Seed at least one row in
  each table (and at least one event for a non-zero `event_log_cursor`).
  Drive the paginator until `cursor=None` and assert the visited
  `body.table` sequence is exactly `(assets, asset_field_values,
  maintenance_records, maintenance_record_field_values)`.
- **Empty intermediate table is skipped.** Seed assets and maintenance
  records but no asset_field_values. Iterate; assert no batch with
  `table=asset_field_values` is ever emitted.
- **`event_log_cursor` is start-snapshot, not end-snapshot.** Seed N
  events. Call paginator once with `cursor=None` (captures
  `start_seq`). Manually append a new event with the
  `event_log_service`. Continue iterating to terminal. Assert
  `event_log_cursor` equals the *pre-extra* seq, not the *post-extra*
  seq.
- **`schema_version` is current at request time.** Seed schema at v1,
  call paginator (assert v1 emitted), apply a schema change to v2,
  call paginator with the previous cursor, assert v2 emitted.

### `test_endpoint_sync_initial.py` (E2E)

Uses the `client` fixture from `tests/conftest.py`:

- `GET /sync/initial` on a fresh tenant returns 200 with
  `cursor=null`, `event_log_cursor=0`, `body.table="assets"`,
  `body.items=[]`.
- Seed an asset via `POST /events`, then `GET /sync/initial`. Body
  contains an `AssetView` for that asset and at least one
  `AssetFieldValueView` (for `col:name`) reachable by walking the
  cursor. Tombstones surface with `deleted=true`.
- Multi-batch round-trip: seed > `results_per_page` rows, drive
  successive `GET /sync/initial?cursor=…`, assemble all `items` and
  assert no duplicates and full coverage.
- Mid-transfer schema-version advance is observable: page 1 returns
  `schema_version=V1`. Commit a schema change (via `POST /schema`).
  Page 2 (driven by the page-1 `cursor`) returns `schema_version=V2`.
  Server keeps emitting; the client-side restart is *out of scope*.
- `GET /sync/initial?results_per_page=0` → 400 problem-details.
- `GET /sync/initial?results_per_page=5001` → 400 problem-details.
- `GET /sync/initial?cursor=not-base64` → 400 problem-details with
  `type` URI leaf `invalid_payload_shape`.
- `GET /sync/initial?cursor=<valid-but-unknown-table>` → 400.
- HLC preservation: every `*_field_values` row in the response
  carries the same `hlc` string the original event used. Compare
  against a known seed.

### `test_sync_cross_tenant_isolation.py`

Indirect-parametrised across two tenants:

- Seed identical scenarios under `t-a` and `t-b` (using the existing
  `seed(..., tenant_id=...)` fixture).
- Under each tenant, `GET /sync/initial` returns rows whose
  `tenant_id` would have been only that tenant (assert by content —
  ids are seeded distinctly per tenant).
- Drive the cursor to completion under `t-a`; assert the same `cursor`
  reused under `t-b` doesn't leak `t-a`'s data (Layer 1 still scopes
  the reads; the cursor's `last_id` is the only state shared and
  decodes the same, but each tenant sees only its own rows at any
  `last_id`).

### Existing tests that don't change

None. The endpoint is purely additive; the `event_log` and projection
table schemas are unchanged.

## Open questions (deliberate decisions made in this spec)

1. **`cursor` is `str`, not `int`** — opaque, base64-encoded JSON.
   Litestar's `CursorPagination[int, T]` couldn't carry both
   `start_seq` and a per-table position, and the items differ in shape
   across batches. Custom envelope wins on clarity here; the cost is
   one bespoke struct family, paid once.
2. **`event_log_cursor` only on terminal batch.** Intermediate batches
   emit `null`. Available-on-every-batch would let a misbehaving client
   commit a partial cursor and skip catch-up; making it explicitly
   terminal forces correct staging.
3. **No HMAC on the cursor.** See §"Cursor encoding". A client that
   tampers only hurts itself; nothing crosses the tenant boundary.
4. **Default 1000, max 5000.** Defensible round numbers per ADR-015's
   "few thousand" guidance, matching the max of the events catch-up
   endpoint for operational consistency.
5. **Properties / name omitted from the wire.** ADR-015 default. The
   client reconstructs them from the per-field rows it receives.
6. **Empty intermediate tables collapse server-side.** The paginator
   skips ahead in the same request so empty tenants return in one
   round-trip rather than four. The fixed `(assets,
   asset_field_values, maintenance_records,
   maintenance_record_field_values)` walk is preserved; only the
   "always emit one batch per table" alternative is rejected.

## Migration

- Pre-release, no migration tooling. The four projection tables already
  exist and the endpoint only adds read paths.
- No wire-format change to existing endpoints.
- `CLAUDE.md` gains a "Initial sync endpoint (`GET /sync/initial`)"
  subsection on ship, matching the existing per-endpoint sections for
  schema / events.
- ADR-015 flips from Proposed to Accepted in the same commit train.
- No new `ErrorCode` value; existing `INVALID_PAYLOAD_SHAPE` covers
  cursor decode failures.
