# Design: `GET /events` for incremental data catch-up

## Status

Drafted 2026-05-18. Closes M2.4 (issue #34). The HTTP catch-up half of ADR-013;
defines the wire envelope reused by the M3 WebSocket fan-out.

## Problem

A returning client has a `last_seen_seq` cursor from a previous initial sync
(M2.3, ADR-015) or a previous catch-up. It needs to pull all `event_log` rows
its tenant has accumulated since that cursor, in `seq` order, in bounded
batches, before it opens a WebSocket and goes live (M3, ADR-013).

Two things have to be true that the current system does not yet provide:

1. **An HTTP endpoint** that returns events for the tenant after a cursor.
2. **A wire envelope** suitable for both this endpoint and the M3 broadcast —
   ADR-013 mandates "the wire format of an event is identical regardless of
   transport." The current `POST /events` payload (`EventEnvelope`) is the
   write-side shape and is missing server-assigned fields the read side needs
   (`seq`, `schema_version`, `received_at`).

There is also one storage gap that this work must close: the `event_log`
table stores `table_name` (= family) and `entity_id` (= instance_id) but
**not** `type_id`. The wire envelope requires `type_id` (it's part of the
`POST /events` shape), so the read side cannot reconstruct envelopes from
the current schema. The cleanest fix is to add a `type_id` column to
`event_log`; pre-release rules (CLAUDE.md) allow the schema change.

## Goals

1. Add `GET /events` that returns the active tenant's events after a cursor,
   in `seq` order, in batches bounded by a `results_per_page` query
   parameter.
2. Define a `RecordedEvent` msgspec struct that is the single source of
   truth for the read-side wire envelope on HTTP **and** the M3 WebSocket.
3. Store `type_id` on `event_log` so the envelope can be reconstructed
   without JOIN-ing the projection.
4. Use Litestar's `CursorPagination[int, RecordedEvent]` as the response
   type, with an `AbstractAsyncCursorPaginator` subclass owning the query.
5. Match the existing event/schema endpoint conventions: tenant scoping via
   listeners, `application/problem+json` on errors, handler-level + E2E
   tests against a real in-memory SQLite.

## Non-goals

- **WebSocket fan-out.** M3. This spec only defines the shared envelope so
  M3 can adopt it without re-design.
- **Schema-version short-circuit on the read.** ADR-013 §"Schema version
  tagging on events" prescribes per-event tagging and client-side gating;
  this endpoint always returns events with their acceptance-time
  `schema_version` regardless of any client-supplied version. The
  `POST /events` schema-version gate is a write-side concern and stays
  there.
- **Pushing events.** That's `POST /events`, already shipped in M1.
- **Server-assigned cursor opacity.** The cursor is the raw `seq`. Clients
  treat it as opaque per ADR-011, but the server makes no obfuscation
  effort.
- **Cleaning up vestigial columns.** `event_log.field_id` is always NULL
  in the M1.5+ design (the body is stored whole in `value_json`). It stays
  in this spec; if anyone wants it gone, file a follow-up.
- **Hard delete / log retention.** Out of scope per ADR-011.
- **Tenant-cursor lookup.** Returning `MAX(seq)` for the tenant is the
  domain of M2.3 (`GET /sync/initial` includes the cursor in its final
  batch). This endpoint advances a cursor the client already has.

## Architecture

### Module layout

```
src/py/novamoc/
├── db/models/data/
│   └── _event.py                       # MODIFIED: add type_id column
├── domain/events/
│   ├── _payloads.py                    # MODIFIED: add RecordedEvent
│   ├── _bundle.py                      # MODIFIED: write type_id on append
│   ├── _pagination.py                  # NEW: EventLogCursorPaginator
│   └── controllers/
│       └── _events.py                  # MODIFIED: add @get("/") read_stream
└── settings.py                         # MODIFIED: event_catchup_batch_size knobs
```

### Storage change: add `type_id` to `event_log`

```python
# src/py/novamoc/db/models/data/_event.py
class EventLog(DefaultBase):
    __tablename__ = "event_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "hlc", name="uq_event_log_tenant_hlc"),
        Index("idx_event_log_tenant_seq", "tenant_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigIntIdentity, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str]
    hlc: Mapped[str]
    schema_version: Mapped[int] = mapped_column(BigInteger)
    table_name: Mapped[str]
    type_id: Mapped[str]              # NEW — user-schema type FK (string-form UUID)
    entity_id: Mapped[str]            # = instance_id
    field_id: Mapped[str | None]
    op: Mapped[EventOp] = mapped_column(Enum(EventOp, native_enum=False))
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    received_at: Mapped[datetime] = mapped_column(DateTimeUTC, server_default=func.now())
```

`type_id` is `Mapped[str]` to match `entity_id` and `tenant_id` — the
existing rows store UUIDs as their string form. No ADR change; ADR-011's
schema example predates the discriminated `family`/`type_id` envelope and
the column is additive.

Write path: `EventServiceBundle.append_event` already has `event.type_id`
in scope. One added field in the `data=` dict:

```python
await self.event_log_service.create(
    data={
        "hlc": event.hlc,
        "schema_version": self.schema_version,
        "table_name": _TABLE_NAMES[event.family],
        "type_id": str(event.type_id),       # NEW
        "entity_id": str(event.instance_id),
        "field_id": None,
        "op": _op_for_body(event.body),
        "value_json": _value_json_for_body(event.body),
    },
    auto_commit=False,
)
```

No migration tooling — the project is pre-release and `metadata.create_all`
on startup recreates the schema. Existing tests run against a function-
scoped in-memory engine; they get the new column automatically.

### Wire envelope: `RecordedEvent`

Added to `domain/events/_payloads.py` alongside the existing structs:

```python
class RecordedEvent(msgspec.Struct, forbid_unknown_fields=True):
    """Server-recorded event, as emitted on read transports (HTTP catch-up
    and the M3 WebSocket fan-out).

    The "write-side" twin is :class:`EventEnvelope`. The read side adds
    the server-assigned fields (``seq``, ``schema_version``,
    ``received_at``) that ``EventEnvelope`` lacks. Body shape is shared
    — clients can pattern-match on ``body`` the same way regardless of
    direction.

    Attributes:
        seq: Replication cursor. Globally monotonic per ADR-011; clients
            treat it as opaque and use it only to advance their cursor.
        schema_version: Acceptance-time schema version, per ADR-013 /
            ADR-009. Drives client-side gating: events with
            ``schema_version > active_schema_version`` are buffered until
            the client accepts the upgrade.
        hlc: LWW key, identical to ``EventEnvelope.hlc``.
        family: Meta-schema family.
        type_id: User-schema type FK.
        instance_id: User-data instance id.
        body: Discriminated event payload (same union as
            :class:`EventEnvelope`).
        received_at: Server-side acceptance timestamp.
    """

    seq: int
    schema_version: int
    hlc: str
    family: EntityFamily
    type_id: UUID
    instance_id: UUID
    body: EventBody
    received_at: datetime
```

The struct is **read-only on the wire**: it's never accepted as input.
Litestar publishes it in the OpenAPI schema under `CursorPagination[int,
RecordedEvent]`.

#### Body reconstruction from `event_log`

```python
def _row_to_event_body(row: EventLog) -> EventBody:
    """Reverse of ``_value_json_for_body`` / ``_op_for_body``."""
    if row.op is EventOp.DELETE:
        return Deactivated()
    # value_json round-trips through msgspec.to_builtins on the write
    # side, so msgspec.convert is the exact inverse. The ``event``
    # discriminator tag in value_json selects the right variant.
    return msgspec.convert(row.value_json, type=EventBody)
```

`Deactivated` is the lone op where `value_json` is NULL by design
(ADR-011 §"Schema: `value_json TEXT, -- NULL for deletes`"). Every
other body type writes its full tagged dict, so the convert is
unambiguous.

The reconstruction is sync, pure, and trivially unit-testable.

### Cursor pagination

Litestar exposes `CursorPagination[C, T]` and
`AbstractAsyncCursorPaginator[C, T]` (reference:
https://docs.litestar.dev/2/reference/pagination.html). The implementation
goes in a new `_pagination.py`:

```python
# src/py/novamoc/domain/events/_pagination.py
from advanced_alchemy.filters import LimitOffset, OrderBy
from litestar.pagination import AbstractAsyncCursorPaginator

from novamoc.db.models.data import EventLog
from novamoc.domain.events._payloads import (
    EntityFamily, RecordedEvent, _row_to_event_body,
)
from novamoc.domain.events.services import EventLogService


class EventLogCursorPaginator(AbstractAsyncCursorPaginator[int, RecordedEvent]):
    """Cursor-paginated reader over ``event_log`` for the active tenant.

    Cursor is the raw ``seq`` value. Semantics:

    * ``cursor=None`` → start from the beginning of the tenant's stream.
    * ``cursor=N`` → return rows with ``seq > N`` (exclusive, per ADR-011).
    * Returned cursor is the ``seq`` of the last row when more remain,
      or ``None`` when the caller has reached the end.

    Tenant scoping is structural: Layer 1 of ``db._listeners`` injects
    ``WHERE tenant_id = <ctx>`` on every read, so no tenant predicate
    appears here.
    """

    def __init__(self, event_log_service: EventLogService) -> None:
        self._service = event_log_service

    async def get_items(
        self, cursor: int | None, results_per_page: int
    ) -> tuple[list[RecordedEvent], int | None]:
        # advanced-alchemy's StatementFilter for ``seq > cursor`` is
        # easiest expressed as a raw kwarg on .list, or via a CollectionFilter.
        # We fetch ``results_per_page + 1`` so we can detect overflow without
        # a separate COUNT.
        filters: list[Any] = [
            OrderBy(field_name="seq"),
            LimitOffset(limit=results_per_page + 1, offset=0),
        ]
        if cursor is not None:
            filters.append(_seq_gt(cursor))
        rows = await self._service.list(*filters)

        has_more = len(rows) > results_per_page
        page = rows[:results_per_page]
        items = [_row_to_recorded_event(row) for row in page]
        next_cursor = page[-1].seq if has_more else None
        return items, next_cursor


def _row_to_recorded_event(row: EventLog) -> RecordedEvent:
    return RecordedEvent(
        seq=row.seq,
        schema_version=row.schema_version,
        hlc=row.hlc,
        family=_FAMILY_BY_TABLE_NAME[row.table_name],
        type_id=UUID(row.type_id),
        instance_id=UUID(row.entity_id),
        body=_row_to_event_body(row),
        received_at=row.received_at,
    )
```

Two small helpers earn their keep:

- `_FAMILY_BY_TABLE_NAME: dict[str, EntityFamily]` — the inverse of
  `_bundle._TABLE_NAMES`. Lives in `_bundle.py` next to its inverse so
  the round-trip stays in one file; `_pagination.py` imports it.
- `_seq_gt(cursor)` — the cleanest spelling of a `seq > ?` predicate via
  advanced-alchemy. Likely a `CollectionFilter`-style or just a raw
  `BinaryExpression` wrapped in advanced-alchemy's filter protocol; the
  exact spelling lands during implementation. If advanced-alchemy makes
  this awkward, the fallback is one ad-hoc `select(EventLog).where(...)`
  via the repository's `session`.

The paginator is wired as a Litestar dependency:

```python
# in controllers/_events.py
async def _provide_event_log_cursor_paginator(
    event_log_service: EventLogService,
) -> EventLogCursorPaginator:
    return EventLogCursorPaginator(event_log_service)
```

### Controller

The `GET /` handler joins the existing `EventsController`:

```python
@get(
    "/",
    responses={
        400: ResponseSpec(
            ProblemDetails,
            description="Invalid cursor or batch size",
            media_type="application/problem+json",
        ),
    },
)
async def read_stream(
    self,
    paginator: EventLogCursorPaginator,
    cursor: Annotated[int | None, Parameter(ge=0)] = None,
    results_per_page: Annotated[
        int, Parameter(ge=1, le=5000)
    ] = 500,
) -> CursorPagination[int, RecordedEvent]:
    return await paginator(cursor=cursor, results_per_page=results_per_page)
```

The `le=5000` and `default=500` are duplicated from `Settings` for the
type-level annotation (Litestar wants literal bounds in the annotation).
The handler reads no `state.settings.app.*` at request time; instead the
controller asserts at import time that the literal bounds match
`AppSettings.event_catchup_max_batch_size` /
`event_catchup_default_batch_size`. If a future change to the settings
fails that assertion the module fails to import — caught by the
existing `pytest` startup. (This minor friction is the cost of using
Litestar's `Annotated[..., Parameter(...)]` form for free OpenAPI; an
alternative is to omit the `le=` constraint and clamp inside
`read_stream`. Acceptable either way.)

The `Parameter(...)` constraints surface bad input as Litestar
`ValidationException`, which the existing `ProblemDetailsPlugin` renders
as 400 `application/problem+json`. No new error code.

`settings` is read at module import for the `le=` / `default=`
constraints. The values live on `AppSettings`:

```python
# settings.py
class AppSettings(msgspec.Struct):
    ...
    event_catchup_default_batch_size: int = 500
    event_catchup_max_batch_size: int = 5000
```

Defaults chosen to: (a) keep typical catch-up responses under a
megabyte at average event size, (b) cap a misbehaving client at 5000
rows / request. Numbers can move under profiling.

### Tenant scoping

No change. The existing tenant-scoping listeners (`db._listeners`,
issue #51) auto-inject `WHERE tenant_id = <ctx>` on every ORM SELECT
that touches a class with a `tenant_id` column. The paginator's
`.list(...)` call goes through `EventLogService.list`, which uses the
repository, which composes the ORM select — Layer 1 covers it.

`TenantContextMiddleware` runs upstream and sets the contextvar from
`request.auth.tenant_id`. The handler does not read tenant directly.

A cross-tenant isolation test (parallel to
`tests/schema/test_cross_tenant_isolation.py`) verifies that a `t-a`
catch-up sees only `t-a`'s events even when `t-b` rows interleave at
adjacent `seq` values.

### Error mapping

| Wire condition                                   | Status | Code |
|--------------------------------------------------|--------|------|
| `cursor` < 0                                     | 400    | (Litestar ValidationException → ProblemDetailsPlugin) |
| `results_per_page` < 1 or > `max_batch_size`     | 400    | same |
| `cursor` not an integer                          | 400    | same |
| Missing / invalid bearer                         | 401    | upstream `AuthenticationMiddleware` |

No new domain error type. Validation errors funnel through the existing
ProblemDetailsPlugin path.

### What stays unchanged

- `EventEnvelope` / `EventBatch` / `EventOutcome` / `EventBatchResponse`
  — the write-side wire structs are untouched.
- `POST /events` controller, dispatch table, handlers, validators — no
  read path lives here.
- The fold / projection writers (`_fold.py`, `_projection.py`,
  `_row_state.py`) — read-only consumers don't touch the fold.
- The existing 12+ event endpoint tests — they still cover the write
  path unchanged.

## Tests

### New unit tests

- `tests/events/test_recorded_event.py` — `_row_to_event_body` round-trip
  for each `(EventBody, op)` cell. Hand-builds `EventLog` instances and
  asserts the body decodes back to the original struct. Includes the
  `Deactivated → value_json=None` branch.
- `tests/events/test_pagination.py` — `EventLogCursorPaginator` unit
  tests against the `services` fixture: empty stream, single page,
  multi-page cursor handoff (assert `cursor` echoes back into a
  subsequent `get_items` call and continues correctly), `results_per_page`
  larger than the stream, exact-page-size boundary.

### New endpoint tests

`tests/events/test_endpoint_catchup.py` (E2E, uses `client` fixture):

- `GET /events/` on a fresh tenant returns `items=[]`, `cursor=None`.
- Seed N events; `GET /events/?results_per_page=N` returns all items,
  `cursor=None`.
- Seed N events; `GET /events/?results_per_page=K` (K < N) returns the
  first K items with a non-null `cursor`. Subsequent
  `GET /events/?cursor=<that>` returns the rest.
- `GET /events/?cursor=-1` → 400 ProblemDetails.
- `GET /events/?results_per_page=0` → 400 ProblemDetails.
- `GET /events/?results_per_page=<max+1>` → 400 ProblemDetails.
- Body round-trip: post `Created` / `Updated` / `Deactivated` /
  `Activated` events, then GET them and assert each `RecordedEvent.body`
  matches the original (modulo server-assigned envelope fields).
- `schema_version` on the read matches the version at acceptance time
  (post a Created at version V1, commit a schema change to V2, GET and
  assert the recorded event still carries V1).

### New isolation test

`tests/events/test_catchup_cross_tenant_isolation.py`:

- Seed events for `t-a` and `t-b` interleaved at adjacent `seq` values.
- Under each tenant context, assert the catch-up response contains only
  that tenant's events and the `cursor` returned matches the tenant's
  own `seq` progression (not the global one).

### Modified existing tests

- `tests/events/test_endpoint_validation.py` — no behaviour change to
  the write path, but the new `type_id` column will appear in
  `event_log` rows. If any test inspects raw rows by-column, update the
  expected row shape. (Most tests black-box through the HTTP response,
  so they're untouched.)
- `tests/conftest.py` — add a small `event_log_service(session)`
  fixture so unit tests can construct `EventLogCursorPaginator` without
  going through the controller. Existing `services` fixture (schema-only
  `ServiceBundle`) is unchanged. Endpoint tests use the existing
  `client` fixture and don't need new fixtures.

## Open questions

These are deliberate decisions made in this spec; calling them out for
the reviewer:

1. **`type_id` as `Mapped[str]` not `Mapped[UUID]` / `GUID`.** Matches
   the existing `entity_id` and `tenant_id` columns — they're string
   UUIDs throughout `event_log`. Switching to `GUID` is a separate
   cleanup that should sweep all three.
2. **Cursor query-string name is `cursor`, not `since`.** Issue #34's
   title uses `?since=<seq>`; Litestar's convention is `?cursor=`. No
   ADR pins the name. Adopting Litestar's convention buys free OpenAPI
   integration and parity with any future paginated endpoint.
3. **Default `results_per_page` of 500, max 5000.** These are
   defensible round numbers, not measured. Subject to revision after
   M3 traffic shows real distributions.
4. **No JOIN-on-read alternative for `type_id`.** Considered and
   rejected: storing `type_id` is small, avoids the projection
   dependency for read, and future-proofs against any later
   hard-delete path. Issue #34's "Critical design gap" section names
   this decision explicitly.

## Migration

- Pre-release, no migration tooling. `metadata.create_all` on startup
  picks up the new column; tests use a function-scoped in-memory
  engine and get the new shape automatically.
- No wire-format change to `POST /events` or its response.
- The CLAUDE.md "Events endpoint (`POST /events`)" subsection gains
  one sentence noting the read-side `GET /events`; or a sibling
  subsection if the prose grows long.
- No new ADR. The decision to use cursor pagination over a custom
  envelope is consistency with Litestar's published pattern, not an
  architectural commitment. ADR-013 already prescribes the per-event
  `schema_version` tag this design carries on `RecordedEvent`.
