# Design: per-event handler dispatch for `POST /events`

## Status

Approved 2026-05-11. Supersedes the controller-resident validator shape in
PR #64; PR #64 will be reshaped to this design before merge.

## Problem

PR #64 (M1.4) adds field-existence and value-type validation to the events
endpoint, but places the orchestrator (`validate_event_values`) at the
controller level — the controller iterates events and, for each one, calls
the shared validator which internally dispatches on body type (`Created` /
`Updated` carry values; `Deactivated` / `Activated` don't) and on
`event.family` to choose the right field service. That shape works, but it
pins all per-event behaviour into one generic function. As M1.5+ adds
business validation (parent rules on `Created`, deleted-target checks on
`Updated`, idempotency, projection writes, log appends), the generic
function either grows uncomfortable or has to be torn apart anyway.

The desired shape is the inverse: the controller validates the *envelope*
(HLC parse, drift bound, schema-version gate) and nothing else; per-event
*handlers* own field/value validation today and grow into business
validation + persistence tomorrow. This mirrors the schema endpoint's
established `_HANDLERS: dict[type, Handler]` pattern (CLAUDE.md §"Schema
endpoint").

## Goals

1. Move all per-event logic out of the controller into per-(event_type,
   family) handler functions.
2. Express the dispatch as a single explicit table — one `rg`-able place
   that enumerates every accepted `(family, body_type)` cell.
3. Keep the field/value-shape validation logic reusable: handlers call
   shared predicates rather than re-implementing them.
4. Land the refactor as an in-place update to PR #64. No behaviour change
   on the wire; only the internal structure shifts.
5. Set up M1.5+ to slot persistence, projection writes, and business rules
   into the same cells without further structural movement.

## Non-goals

- Implementing M1.5 (persistence + projection writes). Handlers stay
  validation-only in this PR; the no-op handlers for `Deactivated` /
  `Activated` exist to make the dispatch table complete.
- Adding parent presence / deleted-target / idempotency checks. Those land
  with M1.5 in the same handlers.
- Cross-request schema caching. The `fields_for` memo is request-scoped
  and dies with the bundle. A longer-lived (process-scoped, keyed on
  `(tenant_id, type_id, schema_version)`) cache would amortise the
  field-set load across many requests but adds invalidation surface and
  isn't justified until profiling says so.
- Adding a `EventOutcome` return value. Handlers return `None` for now;
  the dispatcher signature can grow a return type later when persistence
  lands.

## Architecture

### Module layout (after the refactor)

```
src/py/novamoc/domain/events/
├── _payloads.py              # unchanged: EventBatch, EventEnvelope, EventBody discriminated union
├── _errors.py                # unchanged: HLCDriftExceededError, SchemaVersionStaleError,
│                             #            UnknownFieldError, ValueTypeMismatchError
├── _hlc.py                   # unchanged
├── _validators.py            # SHRUNK: shared helpers only (predicates + per-key validator)
├── _bundle.py                # NEW: EventServiceBundle (frozen dataclass)
├── _dispatch.py              # NEW: _HANDLERS table + dispatch(event, ...)
├── _handlers/
│   ├── __init__.py
│   ├── asset.py              # NEW: created / updated / deactivated / activated
│   └── maintenance_record.py # NEW: created / updated / deactivated / activated
└── controllers/
    ├── __init__.py
    └── _events.py            # SLIMMED: envelope gates only, then dispatch per event
```

### Dispatch key

Schema commands have a unique struct class per cell, so the schema
dispatch keys on `type(request)`. Events differ: a `Created` body is the
same `Created` class regardless of family (the family lives on the
envelope). The events dispatch key is therefore a tuple:

```python
# _dispatch.py
_HANDLERS: dict[tuple[EntityFamily, type[EventBody]], Handler] = {
    (EntityFamily.ASSET, _payloads.Created):     asset.created,
    (EntityFamily.ASSET, _payloads.Updated):     asset.updated,
    (EntityFamily.ASSET, _payloads.Deactivated): asset.deactivated,
    (EntityFamily.ASSET, _payloads.Activated):   asset.activated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Created):     maintenance_record.created,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Updated):     maintenance_record.updated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Deactivated): maintenance_record.deactivated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Activated):   maintenance_record.activated,
}


async def dispatch(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    await _HANDLERS[(event.family, type(event.body))](services, auth, event)
```

Eight cells, all enumerated. A new event type (e.g. `Reparented`) is
caught at decode time if it's not in `EventBody`; a new family adds a row
per existing event type. There is no fallback / wildcard — coverage gaps
fail loudly with `KeyError` and are caught by tests.

### Handler signature

Mirrors the schema endpoint:

```python
# _handlers/asset.py
async def created(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast("_payloads.Created", event.body)
    fields_by_id = await services.fields_for(event.family, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)

async def updated(...): ...      # same shape, body = Updated
async def deactivated(...): pass  # no values, no validation; placeholder for M1.5
async def activated(...): pass    # same
```

The `cast(...)` is a localised acknowledgement that dispatch has already
narrowed the body type — the type-checker can't see through the table.
Handlers stay tiny in M1.4; they're the place future M1.5 business logic
slots into without another round of dispatcher changes.

`maintenance_record.py` is the same shape with the
maintenance-record field service substituted.

### Query budget

PR #64's `validate_event_values` issued one `SELECT` per user-field key
(`get_one_or_none(id=field_id)`), so a batch of N events with M user
fields each cost O(N×M) round-trips. The reshape collapses that to **one
`SELECT` per unique `(family, type_id)` in the batch**, regardless of
how many events address that type or how many fields each event carries:

* The handler calls `services.fields_for(family, type_id)`, which loads
  the type's full field set on first use and caches the result on the
  bundle.
* Subsequent events in the same batch addressing the same type get the
  cached map without a round-trip.
* Validation against the loaded map is a pure dict lookup.

Cross-type field IDs are flagged structurally — if a field's ID is not
in the loaded map, it's unknown for this type, and the explicit
`parent_id != event.type_id` check goes away.

The bundle is per-request, so cache lifetime is the request. Schema
cannot change mid-request (the transaction holds the snapshot), so no
invalidation is needed.

### Service bundle

```python
# _bundle.py
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class EventServiceBundle:
    asset_type_field_service: AssetTypeFieldService
    maintenance_record_type_field_service: MaintenanceRecordTypeFieldService
    _fields_cache: dict[
        tuple[EntityFamily, UUID],
        dict[UUID, AssetTypeField | MaintenanceRecordTypeField],
    ] = field(default_factory=dict)

    async def fields_for(
        self, family: EntityFamily, type_id: UUID
    ) -> dict[UUID, AssetTypeField | MaintenanceRecordTypeField]:
        """Return the type's full field set, loading once per request.

        Subsequent calls for the same ``(family, type_id)`` return the
        cached map without a round-trip. The cache lives for the bundle
        instance, which is built per request — schema cannot change
        mid-request (the transaction holds the snapshot), so no
        invalidation is needed.
        """
        key = (family, type_id)
        cached = self._fields_cache.get(key)
        if cached is not None:
            return cached
        service = (
            self.asset_type_field_service
            if family is EntityFamily.ASSET
            else self.maintenance_record_type_field_service
        )
        rows = await service.list(parent_id=type_id)
        loaded = {r.id: r for r in rows}
        self._fields_cache[key] = loaded
        return loaded
```

Built in the controller via a DI provider that pulls each service from the
existing `create_service_dependencies(...)`-style wiring. `frozen=True` +
a `field(default_factory=dict)` works: frozen prevents rebinding the
attribute, but the dict it points at is freely mutable — which is what
the memo needs.

The bundle is deliberately small in M1.4 and grows in M1.5 (event log
service, projection writers). `SchemaChangeLogService` does **not** join
the bundle — it's only used by the controller for the batch-level
schema-version gate. Per-event handlers have no business with it.

Mixed responsibility (DI + per-request memo) is intentional: a separate
`FieldsLoader` object would always be passed in lockstep with the
bundle, so the second object would not earn its keep.

### Shared helpers in `_validators.py`

`_validators.py` keeps the predicate machinery but drops the orchestrator
and the per-key service dependency. After the refactor it exports:

```python
# pure, sync, handler-callable
def matches_data_type(value: Any, data_type: FieldDataType) -> bool: ...
def json_type_name(value: Any) -> str: ...

def validate_values(
    *,
    event: EventEnvelope,
    values: dict[str, Any],
    fields_by_id: dict[UUID, AssetTypeField | MaintenanceRecordTypeField],
) -> None:
    """Validate every key/value pair in ``values`` against the loaded
    field set.

    Pure, synchronous. Iterates keys, classifies each as a UUID user
    field (looked up in ``fields_by_id``) or a ``col:<name>`` projection
    column (matched against ``_RESERVED_COLS`` / ``_USER_WRITABLE_COLS``),
    and validates the value's JSON shape against the resolved
    ``FieldDataType``.

    Raises PayloadShapeError / UnknownFieldError / ValueTypeMismatchError
    on the first offending key, with the same codes and extension
    members as the M1.4 implementation.
    """
```

Internals (`_RESERVED_COLS`, `_USER_WRITABLE_COLS`, the
`_DATA_TYPE_PREDICATES` table, the `col:` / UUID split) stay private to
the module. The `_values_for_validation` extractor and the per-key
async `validate_field_value` both go away — dispatch resolves body type
ahead of any value inspection, and the handler hands `validate_values`
a fully-loaded field map.

`validate_values` is sync because all I/O has already happened by the
time it runs. That makes it trivially unit-testable in isolation: pass
a hand-built `fields_by_id` dict and assert on the raised exception.

### Controller

```python
class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = (
        {"drift_limit_seconds": Provide(_provide_drift_limit_seconds)}
        | providers.create_service_dependencies(SchemaChangeLogService, "schema_change_log_service")
        | providers.create_service_dependencies(AssetTypeFieldService, "asset_type_field_service")
        | providers.create_service_dependencies(MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service")
    )

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(
        self,
        data: _payloads.EventBatch,
        drift_limit_seconds: float,
        schema_change_log_service: SchemaChangeLogService,
        asset_type_field_service: AssetTypeFieldService,
        maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
        auth: RequestAuth,
    ) -> None:
        # 1. Schema-version gate (batch-level).
        current_version = await schema_change_log_service.current_version()
        if data.schema_version != current_version:
            raise SchemaVersionStaleError(...)

        server_now_ms = wall_now_ms()
        limit_ms = int(drift_limit_seconds * 1000)
        services = EventServiceBundle(
            asset_type_field_service=asset_type_field_service,
            maintenance_record_type_field_service=maintenance_record_type_field_service,
        )

        # 2. Per-event envelope checks, then dispatch.
        for event in data.events:
            _parse_and_check_drift(event, server_now_ms, limit_ms, drift_limit_seconds)
            await dispatch(services, auth, event)
```

`_parse_and_check_drift` is a private helper inside the controller module
(or a free function in `_hlc.py`) that owns HLC parse + drift assertion.
The controller does **not** import `_validators` or any handler module —
its only events-domain import for the per-event loop is `dispatch`.

### What stays unchanged

- `_payloads.py` — wire structs untouched.
- `_errors.py` — the two new exceptions (`UnknownFieldError`,
  `ValueTypeMismatchError`) keep their current shape; they're raised from
  the shared helper, not from a controller function, but the contract is
  identical.
- `_problem_details.py` — title / status mappings stay.
- `docs/problems/unknown_field.md`, `value_type_mismatch.md` — unchanged.
- The 12 endpoint tests in `tests/events/test_endpoint_validation.py` —
  they black-box the endpoint and stay green without modification.

## Changes to PR #64 (concretely)

1. **Add** `_bundle.py` with `EventServiceBundle` (services + per-request
   `fields_for` memo).
2. **Add** `_dispatch.py` with `_HANDLERS` and `dispatch`.
3. **Add** `_handlers/__init__.py`, `_handlers/asset.py`,
   `_handlers/maintenance_record.py`.
4. **Shrink** `_validators.py`:
   * Promote `_json_type_name` → `json_type_name`, `_matches_data_type` →
     `matches_data_type` (public).
   * Replace `_validate_col_key` + `_validate_user_field_key` +
     `_validate_value` + `validate_event_values` with one public
     **synchronous** `validate_values` that iterates the values dict,
     classifies each key, and validates the value against the
     handler-supplied `fields_by_id` map. No service calls happen here.
   * Delete `_values_for_validation`.
5. **Slim** `controllers/_events.py`:
   * Drop the import of `validate_event_values`.
   * Add the import of `dispatch` from `_dispatch`.
   * Build `EventServiceBundle` once per request, pass it through.
   * Replace the inline `await validate_event_values(...)` with
     `await dispatch(services, auth, event)`.
6. **Module docstrings**:
   * `controllers/_events.py` docstring: keep the three gates list, but
     reword "per-event schema validation" as "per-event handler dispatch
     (which owns field/value validation today and will own persistence
     in M1.5+)".
   * `_validators.py` docstring: reword as "shared validation helpers
     called by `_handlers/*`; the controller no longer reaches into this
     module directly".

## Tests

### Existing tests

* `tests/events/test_endpoint_validation.py` — 12 endpoint tests. Stay
  black-box, stay green.
* `tests/events/test_validators.py` — rewritten around the new
  `validate_values` surface. With validation now sync and parameterised
  by a `fields_by_id` map, the unit tests hand-build the map and assert
  on raised exceptions directly. Covers the full matrix that the M1.4
  file covers today (predicates + `col:` rules + cross-type rejection +
  null passthrough) without going through the DB. The `json_type_name`
  and `matches_data_type` predicates retain dedicated tests as pure
  helpers.

### New tests

* `tests/events/test_dispatch.py` — one test that the `_HANDLERS` table
  covers every `(EntityFamily, type(body))` pair. Implementation:
  iterate `EntityFamily` × `get_args(EventBody)`, assert each cell is in
  the table. Catches drift if a new family or event type is added without
  a handler.
* `tests/events/test_bundle.py` — assert that calling `fields_for` twice
  for the same `(family, type_id)` issues exactly one `SELECT`. Cheapest
  implementation: wrap the field service in a thin counting spy, build
  the bundle around the spy, call `fields_for` twice, assert the spy's
  call count is 1. Catches accidental cache bypass.
* `tests/events/test_handlers_asset.py` — handler-level tests that
  exercise the typed-exception contract directly (mirroring
  `tests/schema/test_handlers_*.py`). One test per handler is enough in
  M1.4; the heavy lifting happens at the endpoint layer. Asserts:
  * `created` with a valid values dict returns `None`.
  * `created` with an unknown field raises `UnknownFieldError`.
  * `updated` with a deactivated field returns `None`.
  * `deactivated` / `activated` return `None` regardless of body content.
* Same for `tests/events/test_handlers_maintenance_record.py`.

`tests/conftest.py`: add an `event_services` fixture returning an
`EventServiceBundle` built against the existing `session` fixture. Tests
that exercise handlers use it directly; tests that go through the
endpoint don't need it.

## Out of scope (defer to M1.5+)

- **Persistence.** Handlers don't write yet — they validate. The event
  log append, the projection upsert, and the field-value upsert all land
  in M1.5+.
- **Business validation.** Parent-required-for-asset rules, deleted-target
  rejection, idempotency via `UNIQUE(tenant_id, hlc)`, and HLC ordering
  invariants live in the same handlers but are written when the
  corresponding M1.5+ work lands. No placeholders / `TODO` stubs in this
  PR.
- **Cross-handler shared business logic.** If M1.5 surfaces a check that
  belongs in both `Created` and `Updated`, factor it then. Don't predict.
- **Outcome return value.** When persistence lands, handlers will return
  an `EventOutcome`-like object so the controller can shape a response
  body. Today they return `None` and the controller responds 202 with no
  body, unchanged.

## Migration

* PR #64 is updated in place — no separate PR for the refactor.
* No wire-format change; no client-visible behaviour change.
* The CLAUDE.md "Schema endpoint (`POST /schema`)" section gains a sibling
  "Events endpoint (`POST /events`)" subsection that describes the same
  pipeline shape (decode → batch gates → dispatch → handler).
* No new ADR. The decision to mirror the schema endpoint's dispatch
  pattern is consistency with an existing decision (ADR-008 / ADR-013),
  not a new architectural commitment.
