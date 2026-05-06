# Tenant Scoping Enforcement Design

## Status

Draft

## Purpose & scope

Make tenant scoping a structural property of the storage layer, not a discipline observed at every call site. Replace ADR-014's "code-review attention to any query that does not visibly scope by tenant" mitigation with three layered framework hooks that (a) auto-inject the tenant predicate on reads, (b) auto-stamp `tenant_id` on inserts, and (c) reject any tenant-scoped-table DML statement that escapes the first two layers without a `tenant_id` predicate.

Resolves issue [#51](https://github.com/shoriminimoe/novamoc/issues/51). Aligned with ADR-017 (tenant resolution from the request envelope) and ADR-014 (row-scoping multi-tenancy, superseded but informational).

In scope:

- Storage-layer enforcement primitives: contextvar, mixin/base, three SQLAlchemy listeners, two typed exceptions.
- Middleware wiring that binds the contextvar to the per-request `RequestAuth.tenant_id`.
- Removal of explicit `tenant_id=` arguments from handler call sites where auto-inject covers them.
- Tests proving every service method scopes correctly under both tenants and that escapes are rejected.

Out of scope:

- The bearer-token resolver / dev-credential model (ADR-017, already shipped via PR #49).
- Adding services for the as-yet-unbuilt EAV / event-log / data-projection tables. Those services land with their own specs; this spec lays the rails so they inherit enforcement for free.
- Any change to ADR-014. ADR-014 is superseded by ADR-017; this spec is *implementation* of ADR-014's row-scoping decision under the request-envelope tenant model from ADR-017.

## Why three layers

Issue #51 calls for queries to be **rejected**, not silently scope-narrowed. Auto-injection alone (Layers 1–2) prevents the leak but rewrites SQL silently — so the listener backstop (Layer 3) is what gives us literal "rejected" semantics on the residual paths that auto-injection cannot reach. Each layer has a single, narrow job:

| Layer | Hook | Covers | Behaviour |
|------|------|--------|-----------|
| 1 | `do_orm_execute` | ORM SELECT against tenant-scoped tables | Inject `tenant_id = <ctx>` predicate via `with_loader_criteria(include_aliases=True)`. Fail closed if no contextvar set. |
| 2 | `before_flush` | New ORM instances of tenant-scoped models | Stamp `tenant_id` from contextvar if unset; raise on cross-tenant write. |
| 3 | `before_execute` | Core-level INSERT/UPDATE/DELETE against tenant-scoped tables | Inspect compiled statement; raise if no `tenant_id` predicate (UPDATE/DELETE) or VALUES key (INSERT). |

Layers 1–2 cover the 99% path that flows through the `advanced_alchemy` repository / unit-of-work. Layer 3 is the structural guarantee for raw `session.execute(insert/update/delete)` paths and any `update_many` / `delete_where` / bulk DML that the repository may dispatch through Core.

## Components

### `db/_tenant_context.py`

```python
from contextvars import ContextVar

current_tenant_id: ContextVar[str | None] = ContextVar(
    "novamoc_current_tenant_id", default=None
)

SKIP_TENANT_FILTER = "novamoc_skip_tenant_filter"  # exec-option key
```

Plus a small `use_tenant(tenant_id)` context manager for tests/scripts that need to set the contextvar outside the HTTP request lifecycle.

### `db/models/_mixins.py`

A new general-purpose mixins module — `_mixins.py`, not scoped to tenancy in its name, so future mixins (timestamping flavours, soft-delete, etc.) can live alongside without renaming. The first inhabitant is `TenantScopedMixin`:

```python
class TenantScopedMixin:
    """Mark a mapped class as tenant-scoped.

    Adds `tenant_id` as a primary-key column with `sort_order=-200`, so
    when composed with a UUID/BigInt PK base the composite PK leads with
    `tenant_id` (ADR-014). Targeted by the three enforcement listeners
    in `db/_listeners.py`.
    """
    tenant_id: Mapped[str] = mapped_column(primary_key=True, sort_order=-200)
```

`TenantScopedAuditBase` is removed. Models compose the mixin with whichever advanced-alchemy base matches their PK and audit needs:

| Table | Composition | Resulting PK |
|-------|------------|--------------|
| `AssetType`, `AssetTypeField`, `MaintenanceRecordType`, `MaintenanceRecordTypeField`, `Asset`, `MaintenanceRecord` | `(TenantScopedMixin, UUIDAuditBase)` | `(tenant_id, id)` |
| `EventLog` | `DefaultBase` + hand-declared `tenant_id: Mapped[str]` (non-PK), sole `seq` PK | `seq` (sole) — see deviation below |
| `SchemaChangeLog` | `(TenantScopedMixin, DefaultBase)` + own application-managed `seq` PK column | `(tenant_id, seq)` (matches today; per-tenant `seq`) |
| `AssetFieldValue`, `MaintenanceRecordFieldValue` | `(TenantScopedMixin, DefaultBase)` + own composite key columns | `(tenant_id, *_id, field_id)` (matches today) |

**`EventLog` is the one synced table that does not inherit the mixin.** SQLAlchemy's SQLite DDL compiler hard-rejects `INTEGER PRIMARY KEY AUTOINCREMENT` on a composite PK (verified empirically during implementation: `sqlalchemy.exc.CompileError: SQLite does not support autoincrement for composite primary keys`). Since ADR-011 requires `seq` to be globally monotonic and that depends on the autoincrement guarantee, `EventLog` keeps the today's shape:

- Sole `seq` PK with `BigIntIdentity` / `autoincrement=True`.
- Hand-declared non-PK `tenant_id: Mapped[str]`.
- Explicit `Index("idx_event_log_tenant_seq", "tenant_id", "seq")` retained — without the composite PK to provide the index for free, the explicit index is needed for per-tenant scans (ADR-011's streaming).
- `UNIQUE(tenant_id, hlc)` retained for idempotent re-delivery.

The hand-declared `tenant_id` column is still picked up by all three enforcement listeners' column-presence heuristic, so EventLog gets the same protection as every other tenant-scoped table — the mixin is convenience, not enforcement.

**`SchemaChangeLog`** keeps its existing composite `(tenant_id, seq)` PK shape — that works because `seq` is `autoincrement=False` (application-managed at insert time, not DB-managed), so the SQLite restriction doesn't apply.

The three enforcement listeners identify "tenant-scoped table" by **column presence**, not by class hierarchy:

```python
def _is_tenant_scoped(table) -> bool:
    return "tenant_id" in table.columns
```

This heuristic is shared across all three listeners, so any table that gains a `tenant_id` column — whether or not it inherits the mixin — is automatically in scope. The mixin's job is convenience and consistency; the listeners' job is enforcement.

### `db/_listeners.py`

Three listeners. Each is a module-level `@event.listens_for(Session, ...)` or `@event.listens_for(Engine, ...)` declaration that attaches to SQLAlchemy's global event system at import time. See *Listener installation* below for the import wiring.

**Layer 1 — `do_orm_execute` on Session:**

```python
@event.listens_for(Session, "do_orm_execute")
def _inject_tenant_filter(state):
    if not state.is_select:
        return
    if state.execution_options.get(SKIP_TENANT_FILTER):
        return
    if not _statement_targets_tenant_scoped_table(state.statement):
        return
    tid = current_tenant_id.get()
    if tid is None:
        raise UnscopedQueryError(
            "Tenant-scoped SELECT attempted without tenant context"
        )
    state.statement = state.statement.options(
        with_loader_criteria(
            lambda cls: "tenant_id" in cls.__table__.columns,
            lambda cls: cls.tenant_id == tid,
            include_aliases=True,
        )
    )
```

**Layer 2 — `before_flush` on Session:**

```python
@event.listens_for(Session, "before_flush")
def _stamp_or_reject_tenant(session, flush_context, instances):
    tid = current_tenant_id.get()
    for obj in session.new:
        if not _instance_is_tenant_scoped(obj):
            continue
        if obj.tenant_id is None:
            if tid is None:
                raise UnscopedQueryError(
                    f"Tenant-scoped INSERT attempted without tenant context: {type(obj).__name__}"
                )
            obj.tenant_id = tid
        elif tid is not None and obj.tenant_id != tid:
            raise CrossTenantWriteError(
                f"INSERT into {type(obj).__name__} for tenant {obj.tenant_id} "
                f"under context {tid}"
            )
```

`session.dirty` is intentionally not walked here. Updates that go through the repository's `update(item_id=(tenant_id, id), ...)` path are scoped by the composite PK in their WHERE clause; updates that go through Core bulk DML are caught by Layer 3.

**Layer 3 — `before_execute` on Engine:**

```python
@event.listens_for(Engine, "before_execute")
def _reject_unscoped_dml(conn, clauseelement, multiparams, params, opts):
    if opts.get(SKIP_TENANT_FILTER):
        return
    if isinstance(clauseelement, Insert):
        table = clauseelement.table
        if _is_tenant_scoped(table) and not _values_carries_tenant(clauseelement, params):
            raise UnscopedQueryError(
                f"INSERT into {table.name} has no tenant_id in VALUES"
            )
    elif isinstance(clauseelement, (Update, Delete)):
        scoped = [t for t in clauseelement.get_final_froms() if _is_tenant_scoped(t)]
        if scoped and not _whereclause_filters_tenant(clauseelement):
            raise UnscopedQueryError(
                f"{type(clauseelement).__name__} against "
                f"{[t.name for t in scoped]} has no tenant_id predicate"
            )
    # SELECTs are owned by Layer 1 and excluded here.
```

Helpers (`_is_tenant_scoped`, `_values_carries_tenant`, `_whereclause_filters_tenant`) live in the same module; their precise shapes are pinned during implementation. The WHERE-clause walk returns True iff a `BinaryExpression` whose left side is the table's `tenant_id` column appears anywhere in the WHERE tree (joins, AND chains, subqueries). Bind params vs literals are both fine; the check is presence-only, not strictness. False negatives become bugs to fix in the listener; false positives by construction don't exist (we only check for column presence in a comparison).

### `db/_errors.py`

```python
class UnscopedQueryError(RuntimeError):
    """A statement against a tenant-scoped table executed without a tenant scope.

    Programming error — handlers should not catch this. Raised by the
    enforcement listeners (db/_listeners.py); response paths let
    it propagate to a 500 from the framework.
    """


class CrossTenantWriteError(RuntimeError):
    """An ORM instance was flushed with a tenant_id different from the
    current contextvar. Programming error or attack — same handling as
    UnscopedQueryError.
    """
```

Both are `RuntimeError` subclasses, **not** `SchemaError` subclasses. They do not get problem-details renderers — they are programming bugs, not user-facing failures, and we want them to crash visibly in CI/dev rather than be swallowed into a 4xx.

### `domain/accounts/_middleware.py` (extension)

`TenantContextMiddleware` is added to the existing `_middleware.py` (which already houses `AuthenticationMiddleware`). It inherits from `litestar.middleware.ASGIMiddleware` (the documented Litestar middleware shape — see https://docs.litestar.dev/2/usage/middleware/creating-middleware.html#extending-asgimiddleware) and implements one method, `handle`, which receives the `next_app` to call after the wrapping work:

```python
from litestar.middleware import ASGIMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send

from novamoc.db._tenant_context import current_tenant_id


class TenantContextMiddleware(ASGIMiddleware):
    async def handle(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        next_app: ASGIApp,
    ) -> None:
        auth = scope.get("auth")
        if auth is None:
            await next_app(scope, receive, send)
            return
        token = current_tenant_id.set(auth.tenant_id)
        try:
            await next_app(scope, receive, send)
        finally:
            current_tenant_id.reset(token)
```

`AbstractAuthenticationMiddleware` doesn't expose an "around" hook in `authenticate_request`, so we layer this second middleware *after* it in the stack. Litestar composes middleware outside-in by list order, so the auth middleware resolves credentials and writes `scope["auth"]` first, then this one wraps the rest of the request in a contextvar token.

### `asgi.create_app` middleware list

```python
middleware=[
    DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
    DefineMiddleware(TenantContextMiddleware),
]
```

`/openapi` is excluded only from `AuthenticationMiddleware`. `TenantContextMiddleware` runs for every request but is a no-op when `scope["auth"]` is `None` — so OpenAPI doc generation is unaffected.

### Listener installation

The three listeners use module-level `@event.listens_for(Session, ...)` and `@event.listens_for(Engine, ...)` declarations, attaching to SQLAlchemy's global event system. Importing `db._listeners` at app startup is enough — `asgi.create_app` and the test `conftest.py` both add the import (the existing `import novamoc.db.models` pattern). No per-engine `install(...)` call needed.

## Handler call-site changes

After this lands, schema handlers call services without naming the tenant:

```python
# Before:
obj = await services.asset_type.get_one_or_none(
    tenant_id=auth.tenant_id, id=req.entity_id
)

# After:
obj = await services.asset_type.get_one_or_none(id=req.entity_id)
```

```python
# Before:
await services.asset_type.create(
    data={"tenant_id": auth.tenant_id, "id": req.entity_id, "name": ...},
    auto_commit=False,
)

# After (tenant_id stamped by Layer 2):
await services.asset_type.create(
    data={"id": req.entity_id, "name": ...},
    auto_commit=False,
)
```

`update` and `delete` keep the composite item_id explicitly because the repository's WHERE is built from the PK columns:

```python
# Unchanged:
await services.asset_type.update(
    data={"active": True},
    item_id=(auth.tenant_id, req.entity_id),
    auto_commit=False,
)
```

Layer 3 catches programming bugs at this surface — passing a single-element item_id by mistake produces an UPDATE without a `tenant_id` WHERE clause, which raises `UnscopedQueryError`.

## Service-layer changes

`list_for_tenant` collapses to `list` on every projection service. The two jobs the method did today — apply the tenant filter, apply deterministic ordering for the strong-ETag contract — split:

- **Tenant filter** is gone; Layer 1 supplies it.
- **Deterministic ordering** moves to the GET /schema controller method, where the strong-ETag is built. The ordering is a read-endpoint concern, not a service concern.

`SchemaChangeLogService.append` and `current_version` simplify: the explicit `where(SchemaChangeLog.tenant_id == tenant_id)` in `current_version` goes away — Layer 1 supplies it. The `append` method's signature drops `tenant_id` (the inserted row gets it stamped by Layer 2). The `current_version` signature drops `tenant_id` too.

If `with_loader_criteria` does not attach to a `select(func.coalesce(func.max(SchemaChangeLog.seq), 0))` (the criteria targets mapped classes; aggregate-only selects may not bind one), `current_version` is rewritten as `select(SchemaChangeLog.seq).order_by(SchemaChangeLog.seq.desc()).limit(1)` — an ORM entity load that loader-criteria definitely sees. The change is settled by a focused test before the rest of the work.

## Tests

Tests live under `tests/db/test_tenant_enforcement.py` and `tests/schema/test_cross_tenant_isolation.py`.

### Cross-tenant isolation (the issue's acceptance-criterion test)

Seed equivalent rows under `t-a` and `t-b` (same names, different ids), then under each contextvar value exercise every service method and assert no leak:

```python
@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_every_service_method_is_tenant_scoped(seed, services, tenant):
    await seed(TWO_TENANT_TRUCK)  # seeds equivalent rows under t-a and t-b
    with use_tenant(tenant):
        # Reads
        all_types = await services.asset_type.list()
        assert {t.tenant_id for t in all_types} == {tenant}
        assert await services.asset_type.count() == 1
        assert await services.asset_type.exists(name="Truck")
        # Get by id-that-exists-in-other-tenant returns None
        other_tenant_id = TWO_TENANT_TRUCK.ids[other_of(tenant)]["asset_type"]["Truck"]
        assert await services.asset_type.get_one_or_none(id=other_tenant_id) is None
        # Mutations don't reach the other tenant
        own_id = TWO_TENANT_TRUCK.ids[tenant]["asset_type"]["Truck"]
        await services.asset_type.update(data={"name": "Lorry"}, item_id=(tenant, own_id))
        # ... assert other tenant's row unchanged
```

The `seed` scenario (`TWO_TENANT_TRUCK`) is a small extension to the existing scenario fixtures: `tenants=["t-a", "t-b"]`, each with one asset type named `"Truck"`.

### Negative tests

- **No tenant context → SELECT raises.** With `current_tenant_id` unset, `await services.asset_type.list()` raises `UnscopedQueryError`.
- **No tenant context → INSERT raises.** Same shape with `services.asset_type.create(...)`.
- **Cross-tenant write raises.** Under `current_tenant_id.set("t-a")`, attempting to flush an `AssetType(tenant_id="t-b", ...)` raises `CrossTenantWriteError`.
- **Listener backstop catches Core bulk DML.** `await session.execute(update(AssetType).values(name="X").where(AssetType.id == some_id))` (no `tenant_id` predicate) raises `UnscopedQueryError`. Same for raw `delete(...)`. Same for raw `insert(AssetType).values(...)` without a `tenant_id` key.
- **`skip_tenant_filter` exec option works.** A SELECT issued with `.execution_options(novamoc_skip_tenant_filter=True)` does not get the predicate injected and does not raise. Used by no production code in v1; documented for the future admin path.

### E2E smoke

The existing schema endpoint E2E suite continues to pass unchanged once handler call sites are simplified — the proof that the auto-inject machinery works through the full stack (middleware → handler → service → DB).

## Migration notes

No data migration. The schema doesn't change — `tenant_id` columns on every tenant-scoped table already exist with the correct shape. This is purely an addition of enforcement listeners + a refactor of the model class hierarchy + simplification of handler call sites.

The model hierarchy change is mostly mechanical:

- `TenantScopedAuditBase` → `(TenantScopedMixin, UUIDAuditBase)` for the six projection tables.
- Hand-declared `tenant_id: Mapped[str] = mapped_column(primary_key=True)` lines on `SchemaChangeLog`, `AssetFieldValue`, `MaintenanceRecordFieldValue` are removed (inherited from the mixin instead).
- `EventLog` is unchanged — its hand-declared `tenant_id: Mapped[str]` (non-PK) and `idx_event_log_tenant_seq` index stay (see *EventLog deviation* in Components above).

ty + the test suite catches any miss.

## Risks

- **Listener for `with_loader_criteria` doesn't fire on a specific statement shape.** The `current_version` aggregate-only SELECT is the canonical risk; mitigated by writing a focused test before adopting and falling back to a rewritten ORM-entity-load form if needed.
- **`include_aliases=True` interaction with future relationship loads.** The codebase has no eager-loaded relationships today. When they appear (assets ↔ field_values, etc.), the loader-criteria mechanism is documented to handle them; we add a focused test at that point.
- **ContextVar leak across tasks.** asyncio's task-local contextvar copy semantics handle this correctly; the middleware's `try/finally` reset is the belt-and-braces guarantee for exception paths.
- **Bulk DML Layer-3 walking complexity.** WHERE-clause inspection is fiddly. Mitigated by keeping the check narrow (presence of a comparison referencing the table's `tenant_id` column, anywhere in the tree) and by writing tests for joins, AND chains, and subquery shapes. False negatives become bugs to fix; false positives by construction don't exist.

## Related

- Issue [#51](https://github.com/shoriminimoe/novamoc/issues/51) — this issue.
- ADR-014 — the row-scoping decision (superseded by ADR-017 but informational for the rationale).
- ADR-017 — tenant resolution from the request envelope; provides the `RequestAuth.tenant_id` that this spec binds to the contextvar.
- PR [#49](https://github.com/shoriminimoe/novamoc/pull/49) — the regression that motivated this issue; reverted within the PR.
