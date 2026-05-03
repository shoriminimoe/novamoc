# Design: `POST /schema` endpoint

## Status

Approved. Revised 2026-05-02 to record the msgspec untagged-union constraint, and again on 2026-05-02 to adopt the API-wide error envelope from ADR-016.

## Scope

This spec covers the **command-side** of the schema endpoint only: `POST /schema`, the synchronous command-and-acknowledge path defined by ADR-008 and ADR-013. Schema **reads** (the cached projection clients use offline; the change-log diff that powers ADR-009's upgrade flow) are deferred to a separate spec.

## Goals

1. Accept the 18 schema commands enumerated in `novamoc.domain.schema._commands.SchemaCommand` over a single `POST /schema` route.
2. Validate `(command, payload)` shape at the request decoder.
3. Validate command against current projection state (existence, lifecycle, name reservation, FK relations).
4. Apply the projection mutation and append one `schema_change_log` row in a single transaction.
5. Return the assigned `seq` (= the tenant's new `schema_version`) as the synchronous acknowledgement.
6. Surface every per-command failure mode through a stable error contract the client can branch on.
7. Expose every command and payload shape in the OpenAPI schema.

## Non-goals

- Schema **read** routes (current projection, change-log diff).
- The `schema_changed` WebSocket broadcast. The endpoint records the integration seam but does not implement the broadcaster.
- Authentication and tenant authorization. Tenant id is taken from the request body per ADR-014's pre-auth caveat.
- Idempotency keys. The flow is synchronous; `UNIQUE` constraints surface duplicate-create attempts as informative errors.

## Architecture

### Module layout

```
src/py/novamoc/domain/schema/
├── _commands.py              # SchemaCommand StrEnum (exists; unchanged)
├── _payloads.py              # NEW: per-command msgspec structs + SchemaRequest tagged union
├── _dispatch.py              # NEW: command-class → handler dispatch table
├── _errors.py                # NEW: typed exceptions + stable error codes
├── _outcomes.py              # NEW: Outcome StrEnum (created|activated|noop|updated|deactivated|cleared|deleted) + SchemaCommitOutcome (named tuple of (schema_version: int, entity_id: UUID, outcome: Outcome, committed_at: datetime))
├── controllers/
│   ├── __init__.py
│   └── _schema.py            # NEW: SchemaController hosting POST /schema
└── services/
    ├── __init__.py
    ├── _asset_type.py                     # exists; flesh out activate/update/deactivate/delete
    ├── _asset_type_field.py               # NEW: + clear
    ├── _maintenance_record_type.py        # NEW
    ├── _maintenance_record_type_field.py  # NEW: + clear
    └── _change_log.py                     # NEW: SchemaChangeLogService.append
```

The placeholder `controllers/_asset_type.py` is removed; commands route through one controller, not per-entity-kind.

### Decoder/dispatch (Option D)

Each command is its own msgspec struct sharing `tag_field="command"`. The 18 structs form a discriminated union typed as the request body of `POST /schema`. Dispatch is by the runtime class of the decoded body, not a `match` statement.

**Constraint resolved during implementation.** msgspec rejects a field whose type is a union of two untagged Structs (e.g., `_AssetTypeDefinition | _Empty`) — *all* members of a Struct union must carry a tag. Tagging the inner payload structs would require a discriminator field on the wire, which is not part of the contract. The resolution: each command's `payload` is a **single struct** with all fields optional. For `activate_*` commands, an empty wire `{}` decodes to a struct whose fields are all `None` (read by the handler as "empty intent" — activate-no-op); a populated wire decodes to a struct with the create-shape fields set (read as "create intent"). For `deactivate_*` / `delete_*` / `clear_*` commands, payload remains `_Empty` (a single struct, no union — works fine). For `update_*` commands, payload is a struct with all fields optional and `omit_defaults=True`. The handler still distinguishes intents from the same struct shape, just by inspecting fields rather than by `isinstance`. OpenAPI publishes one schema per command's payload, which is cleaner than a `oneOf` over `definition | empty` would have been.

```python
# _payloads.py
import msgspec
from uuid import UUID

class _AssetTypeDefinition(msgspec.Struct):
    name: str

class _AssetTypeUpdate(msgspec.Struct, omit_defaults=True):
    name: str | None = None

class _Empty(msgspec.Struct, forbid_unknown_fields=True):
    pass  # forbid_unknown_fields makes `{"x": 1}` a decoder error rather than silently accepted

class ActivateAssetType(msgspec.Struct, tag="activate_asset_type", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeDefinition | _Empty

class UpdateAssetType(msgspec.Struct, tag="update_asset_type", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeUpdate

class DeactivateAssetType(msgspec.Struct, tag="deactivate_asset_type", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _Empty

class DeleteAssetType(msgspec.Struct, tag="delete_asset_type", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _Empty

# Field-level commands carry the parent type id in the payload's create-shape.
class _AssetTypeFieldDefinition(msgspec.Struct):
    asset_type_id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, object] | None = None

class _AssetTypeFieldUpdate(msgspec.Struct, omit_defaults=True):
    name: str | None = None
    data_type: FieldDataType | None = None
    validation: dict[str, object] | None = None

class ActivateAssetTypeField(msgspec.Struct, tag="activate_asset_type_field", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeFieldDefinition | _Empty

class UpdateAssetTypeField(msgspec.Struct, tag="update_asset_type_field", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _AssetTypeFieldUpdate

class DeactivateAssetTypeField(msgspec.Struct, tag="deactivate_asset_type_field", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _Empty

class ClearAssetTypeField(msgspec.Struct, tag="clear_asset_type_field", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _Empty

class DeleteAssetTypeField(msgspec.Struct, tag="delete_asset_type_field", tag_field="command"):
    tenant_id: str
    entity_id: UUID
    payload: _Empty

# Eight more for MaintenanceRecordType / MaintenanceRecordTypeField follow the same pattern.

SchemaRequest = (
    ActivateAssetType | UpdateAssetType | DeactivateAssetType | DeleteAssetType
    | ActivateAssetTypeField | UpdateAssetTypeField | DeactivateAssetTypeField | ClearAssetTypeField | DeleteAssetTypeField
    | ActivateMaintenanceRecordType | UpdateMaintenanceRecordType | DeactivateMaintenanceRecordType | DeleteMaintenanceRecordType
    | ActivateMaintenanceRecordTypeField | UpdateMaintenanceRecordTypeField | DeactivateMaintenanceRecordTypeField | ClearMaintenanceRecordTypeField | DeleteMaintenanceRecordTypeField
)
```

The 18-member tagged union is what Litestar's OpenAPI generator surfaces as `oneOf` with `command` as discriminator — every command and its exact payload shape is in the published schema.

```python
# _dispatch.py
from typing import Awaitable, Callable, TypeAlias

Handler: TypeAlias = Callable[[ServiceBundle, SchemaRequest], Awaitable[SchemaCommitOutcome]]

_HANDLERS: dict[type, Handler] = {
    ActivateAssetType:                       handlers.asset_type.activate,
    UpdateAssetType:                         handlers.asset_type.update,
    DeactivateAssetType:                     handlers.asset_type.deactivate,
    DeleteAssetType:                         handlers.asset_type.delete,
    ActivateAssetTypeField:                  handlers.asset_type_field.activate,
    UpdateAssetTypeField:                    handlers.asset_type_field.update,
    DeactivateAssetTypeField:                handlers.asset_type_field.deactivate,
    ClearAssetTypeField:                     handlers.asset_type_field.clear,
    DeleteAssetTypeField:                    handlers.asset_type_field.delete,
    ActivateMaintenanceRecordType:           handlers.maintenance_record_type.activate,
    UpdateMaintenanceRecordType:             handlers.maintenance_record_type.update,
    DeactivateMaintenanceRecordType:         handlers.maintenance_record_type.deactivate,
    DeleteMaintenanceRecordType:             handlers.maintenance_record_type.delete,
    ActivateMaintenanceRecordTypeField:      handlers.maintenance_record_type_field.activate,
    UpdateMaintenanceRecordTypeField:        handlers.maintenance_record_type_field.update,
    DeactivateMaintenanceRecordTypeField:    handlers.maintenance_record_type_field.deactivate,
    ClearMaintenanceRecordTypeField:         handlers.maintenance_record_type_field.clear,
    DeleteMaintenanceRecordTypeField:        handlers.maintenance_record_type_field.delete,
}

async def dispatch(services: ServiceBundle, request: SchemaRequest) -> SchemaCommitOutcome:
    return await _HANDLERS[type(request)](services, request)
```

`ServiceBundle` is the small container that the controller hands to handlers, holding the four entity-kind services and the `SchemaChangeLogService`. Litestar dependency injection assembles it per-request from the same `AsyncSession`.

### Controller

```python
# controllers/_schema.py
from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, post

class SchemaController(Controller):
    path = "/schema"
    dependencies = providers.create_service_dependencies(
        AssetTypeService, "asset_type_service",
    ) | providers.create_service_dependencies(
        AssetTypeFieldService, "asset_type_field_service",
    ) | providers.create_service_dependencies(
        MaintenanceRecordTypeService, "maintenance_record_type_service",
    ) | providers.create_service_dependencies(
        MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service",
    ) | providers.create_service_dependencies(
        SchemaChangeLogService, "schema_change_log_service",
    )

    @post("/")
    async def post(
        self,
        data: SchemaRequest,
        asset_type_service: AssetTypeService,
        asset_type_field_service: AssetTypeFieldService,
        maintenance_record_type_service: MaintenanceRecordTypeService,
        maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
        schema_change_log_service: SchemaChangeLogService,
    ) -> SchemaResponse:
        services = ServiceBundle(
            asset_type=asset_type_service,
            asset_type_field=asset_type_field_service,
            maintenance_record_type=maintenance_record_type_service,
            maintenance_record_type_field=maintenance_record_type_field_service,
            change_log=schema_change_log_service,
        )
        outcome = await dispatch(services, data)
        return SchemaResponse(
            schema_version=outcome.schema_version,
            entity_id=outcome.entity_id,
            outcome=outcome.outcome.value,
            committed_at=outcome.committed_at,
        )
```

The controller is registered in `asgi.create_app()`'s `route_handlers=[...]`.

### Handler shape

Every handler follows the same template: lookup-or-fail, validate state transition, mutate via service, append change-log row, return outcome. Example for `update_asset_type`:

```python
# services/_handlers/asset_type.py (or methods on the service classes themselves —
# see "Service vs handler module" trade-off below)

async def update(services: ServiceBundle, req: UpdateAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND, kind="asset_type")
    payload = msgspec.to_builtins(req.payload, omit_defaults=True)
    if not payload:
        # update with no changes is a 400 — clients should not send these
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.asset_type.update(
            data=payload, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
    except IntegrityError as exc:
        # UNIQUE(tenant_id, name) — rename collided
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.UPDATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(
        schema_version=row.seq,
        entity_id=req.entity_id,
        outcome=Outcome.UPDATED,
        committed_at=row.committed_at,
    )
```

`activate` is the multi-branch handler that implements ADR-008's create-or-activate matrix:

```python
async def activate(services: ServiceBundle, req: ActivateAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    payload_is_empty = isinstance(req.payload, _Empty)

    if obj is None:
        if payload_is_empty:
            raise ConflictError(code=ErrorCode.DEFINITION_REQUIRED)
        # create
        defn: _AssetTypeDefinition = req.payload
        try:
            await services.asset_type.create(
                {"tenant_id": req.tenant_id, "id": req.entity_id, "name": defn.name, "active": True},
                auto_commit=False,
            )
        except IntegrityError as exc:
            raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
        outcome = Outcome.CREATED
    elif not obj.active:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.NAME_IS_DEACTIVATED)
        await services.asset_type.update(
            data={"active": True}, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    else:  # active
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.USE_UPDATE)
        outcome = Outcome.NOOP

    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)
```

`deactivate`, `delete`, and `clear_*_field` follow analogous templates. `delete_*` cascades via the FK `ondelete="CASCADE"` already on the field tables; the handler issues a hard `delete` on the projection row.

`clear_*_field` only mutates per-field projections (`*_field_values`) and the `properties` JSON on entities of that field's parent type. Those projections are not yet modeled in `db.models.data`; this handler's logic stubs out the value-projection wipe with a TODO referencing the data-projection spec, while still appending its `schema_change_log` row. (Filed as a known gap — see "Open questions" below.)

### Service vs handler module

Two reasonable placements for the per-command handler functions:

- Methods on the service class (e.g., `AssetTypeService.activate`).
- Free functions in a sibling `_handlers/<entity_kind>.py` module that take a `ServiceBundle`.

I prefer the second. Handlers need cross-cutting access (the entity-kind service **and** the change-log service, plus the ability to look up parent rows on field commands), so making them service methods either bloats the service or forces awkward setter injection. Free functions parameterized by the bundle are the cleanest fit and keep the entity-kind services thin.

The existing TODO comment on `AssetTypeService.activate` should be moved to the new `_handlers/asset_type.py:activate` module-level docstring.

### Errors

Typed exceptions: `SchemaCommandError` with `PayloadShapeError`, `ConflictError`, `EntityNotFoundError` subclasses, and an `ErrorCode` enum for stable identifiers. Rendering is the app-level layer described in ADR-016; the controller registers no exception handlers itself. Each `ErrorCode` has a fixed `title` and a stable `type` URI of the form `urn:novamoc:problems:<code>`.

### Response envelopes

Success (200):
```json
{
  "schema_version": 1234,
  "entity_id": "01J...",
  "outcome": "created",
  "committed_at": "2026-05-01T12:34:56.789Z"
}
```

`outcome` is one of `created | activated | noop | updated | deactivated | cleared | deleted`.

Failure (409, `application/problem+json` per ADR-016):
```json
{
  "type": "urn:novamoc:problems:name_reserved",
  "title": "Name reserved",
  "status": 409,
  "detail": "Name is already in use by another entity.",
  "instance": "urn:uuid:01958f3b-3b9f-7d3a-89aa-000000000001",
  "name": "Truck"
}
```

Per-error extras (e.g., the conflicting `name` for `name_reserved`) ride as top-level keys; consumers ignore unknown fields.

## Data flow & transactional contract

1. Litestar decodes the request body into one of the 18 structs in `SchemaRequest`. Unknown commands and bad payload shapes fail here with 400 / `invalid_payload_shape`.
2. The route handler builds the `ServiceBundle` from injected per-request services (all sharing the same `AsyncSession`).
3. `dispatch(bundle, req)` looks up the handler by `type(req)`.
4. The handler reads the relevant projection row, validates the transition, mutates the projection (`auto_commit=False`), and appends a `schema_change_log` row.
5. On success, the route returns `SchemaResponse`. The asgi-configured `before_send_handler="autocommit"` commits the transaction. The new row's `seq` is the tenant's new `schema_version` (ADR-008).
6. On any raised exception inside the handler, Litestar's exception handler returns the error envelope and the request rolls back via the same `autocommit` machinery (rollbacks happen on non-2xx).

The single-transaction guarantee follows from the request-scoped session and `before_send_handler="autocommit"`. No handler issues an explicit `commit()`.

## Tenant scoping

Per ADR-014, `tenant_id` is read from the request body. Every handler passes it as the leading filter on every query. There is no global "current tenant" — it travels with each command. Once authentication lands, the tenant id will move to a request-scoped dependency that's validated against the authenticated principal; the handler signatures continue to take it explicitly so the migration is local.

## Schema-changed broadcast (out of scope)

The endpoint emits no broadcast today. The integration point — "after a schema commit, fan-out a `schema_changed` notification to that tenant's WebSocket subscribers" — is named in the design doc but implemented in the sync-layer spec. The handler returns `SchemaCommitOutcome` to the controller; a future broadcaster will subscribe to a post-commit hook (likely SQLAlchemy `after_commit` on the session, scoped to schema mutations) rather than threading anything through `SchemaController`.

## Validation matrix

The behaviour the endpoint enforces, by `(command, projection state)`:

| Verb | Missing | Deactivated | Active |
|---|---|---|---|
| `create_*` | 200 `created` | 409 `name_reserved` | 409 `name_reserved` |
| `activate_*` | 404 `entity_not_found` | 200 `activated` | 200 `noop` |
| `update_*` | 404 `entity_not_found` | 200 `updated` | 200 `updated` |
| `deactivate_*` | 404 `entity_not_found` | 200 `noop` | 200 `deactivated` |
| `clear_*_field` | 404 `entity_not_found` | 200 `cleared` | 200 `cleared` |
| `delete_*` | 404 `entity_not_found` | 200 `deleted` | 200 `deleted` |

`update_*` against a deactivated row is allowed.

`create_*_field` additionally enforces that the parent type exists. If the parent type is missing → 409 `parent_type_not_found`; if it is deactivated, the field create is **allowed** (a hidden type can still have its field schema edited). The implementation reads the parent row before insert and emits the parent-state error before ever touching the field projection.

`update_*_field`, `activate_*_field`, `deactivate_*_field`, `clear_*_field`, and `delete_*_field` against a row whose parent type was hard-deleted will see the field row already removed by FK cascade — the result is 404 `entity_not_found`. Deactivated-parent does not trigger any field-level error since the field row remains.

## OpenAPI

Because `SchemaRequest` is a tagged union of msgspec structs, Litestar publishes:

- A `oneOf` with 22 variants, one per command (4 entity kinds × verbs: `create_*`, `activate_*`, `update_*`, `deactivate_*`, plus `clear_*_field` and `delete_*` where applicable), with `type` as the discriminator (snake_case via the base-class tag callable).
- Each variant's `payload` field is a single struct: `_Empty` for verbs that take no payload (`activate_*`, `deactivate_*`, `clear_*_field`, `delete_*`), `_*CreatePayload` for `create_*`, `_*UpdatePayload` for `update_*`.
- The `SchemaResponse` renders as a plain object schema. Error responses reference `ProblemDetails` from `novamoc.api._problem_details` per ADR-016.

The published schema is the source of truth for client SDK generation and the front-end's schema-editor wire layer.

## Testing strategy

Three layers, all hitting a real SQLite per the `db/` layer convention recorded in feedback memory:

1. **Decoder tests** (`tests/schema/test_payloads.py`). Round-trip every command's wire shape through msgspec and assert the variant produced. Negative cases for missing tag, unknown tag, malformed payload, wrong payload shape per command.
2. **Handler tests** (`tests/schema/test_handlers/test_<entity_kind>.py`). Each handler has its own file. Cover every cell of the validation matrix. Asset-type and maintenance-record-type handlers are nearly symmetric — their tests share a parameterised fixture.
3. **End-to-end controller tests** (`tests/schema/test_endpoint.py`). Drive `POST /schema` through Litestar's test client. Verify the response envelope, the `schema_change_log` row count, the projection state, and the rollback-on-error contract (no row appended on a 4xx).

## Migration / data backfill

None. New endpoint over existing tables.

## Open questions / known gaps

1. **`clear_*_field` value-wipe.** The handler must wipe `*_field_values` rows and strip the field key from `properties` JSON on every entity of the parent type (ADR-008). Those projections are not yet modeled in `db.models.data`. This handler ships with a TODO that asserts an empty value-projection in tests; the wipe is implemented when the data-projection spec lands.
2. **`delete_asset_type` cascade.** ADR-008 says a type-level delete "removes all of its fields and all entities of that type along with their values". The field cascade is wired (FK `ondelete="CASCADE"`); the entity / value cascade depends on the data-projection schema and is gated by the same data-projection spec.
3. **`actor_id`.** The `schema_change_log.actor_id` column stays null until auth lands. Documented; no work in this spec.
4. **Rate / size limits.** None enforced. The endpoint accepts one command per request; if abuse becomes a concern a Litestar middleware can cap request body size and per-tenant rate, separately from this design.
