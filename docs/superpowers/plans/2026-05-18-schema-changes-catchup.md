# Schema Changes Catch-up Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GET /schema/changes?since=<seq>&limit=<n>` per the design at `docs/superpowers/specs/2026-05-18-schema-changes-catchup-design.md` — a bounded, transactionally-consistent stream of accepted schema commands for the active tenant, the server side of ADR-009's catch-up flow.

**Architecture:** New `@get("/changes")` handler on the existing `SchemaController`. Reuses `SchemaChangeLogService.current_version()` for the snapshot read; adds one `list_changes_after(since, limit)` method to the same service for the page. Response shape extends `_read_payloads.py` with a new `SchemaChangeView` row struct and a `SchemaChangesResponse` envelope. Batch-size cap lives as an `AppSettings` field, injected via the same `Provide(_provide_<name>)` pattern `EventsController` already uses. Bounds errors raise `PayloadShapeError(code=INVALID_PAYLOAD_SHAPE)` — no new `ErrorCode` values.

**Tech Stack:** Python 3.14, Litestar, msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, pytest (asyncio auto mode), uv, ruff, ty.

---

## File map

**Created:**
- `tests/schema/test_changes_endpoint_e2e.py` — E2E HTTP tests (200 empty / 200 populated / paging / cursor semantics / range errors / auth).
- `tests/schema/test_changes_service.py` — service-level tests for `list_changes_after`.
- `tests/test_config.py` (new) or extend an existing test — env-var parsing for the new `_int_env` and `schema_changes_max_batch_size` field. **Decision:** colocate in a new `tests/test_config.py`. (No existing file covers `config.py`; this is the first one.)

**Modified:**
- `src/py/novamoc/config.py` — add `_int_env` helper (sibling of `_float_env`); add `AppSettings.schema_changes_max_batch_size: int` reading `NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE` (default `500`).
- `src/py/novamoc/domain/schema/_read_payloads.py` — add `SchemaChangeView` (row struct) and `SchemaChangesResponse` (envelope).
- `src/py/novamoc/domain/schema/services/_change_log.py` — add `list_changes_after(*, since: int, limit: int) -> Sequence[SchemaChangeLog]`.
- `src/py/novamoc/domain/schema/controllers/_schema.py` — add `_provide_max_batch_size` DI provider; register it in `dependencies`; add the `@get("/changes")` handler.
- `tests/schema/test_cross_tenant_isolation.py` — add one test asserting `list_changes_after` is per-tenant.

---

## Conventions

- **TDD throughout.** Every behavioural task starts with a failing test. Watch the test fail before implementing.
- **No DB mocks.** All DB-touching tests use the real in-memory aiosqlite (per `tests/conftest.py`).
- **`uv run` everything.** Tests, lint, type-check all go through `uv run` so the project's pinned deps and Python 3.14 toolchain are used.
- **`pytest` is in asyncio auto mode** — async tests do not need `@pytest.mark.asyncio`.
- **Frequent commits.** One commit per task; the working tree is left clean and tests passing at every commit boundary. Hooks are honoured (no `--no-verify`).
- **No new `ErrorCode` values.** Reuse `INVALID_PAYLOAD_SHAPE` for query-param range errors.

---

## Task 1: Add `schema_changes_max_batch_size` to `AppSettings`

**Files:**
- Modify: `src/py/novamoc/config.py`
- Test: `tests/test_config.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
"""Env-var parsing for AppSettings."""

from __future__ import annotations

import pytest

from novamoc.config import AppSettings


def test_schema_changes_max_batch_size_defaults_to_500(monkeypatch) -> None:
    monkeypatch.delenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", raising=False)
    assert AppSettings().schema_changes_max_batch_size == 500


def test_schema_changes_max_batch_size_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", "42")
    assert AppSettings().schema_changes_max_batch_size == 42


def test_schema_changes_max_batch_size_rejects_non_integer(monkeypatch) -> None:
    monkeypatch.setenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", "not-a-number")
    with pytest.raises(ValueError, match="cannot parse"):
        AppSettings()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`

Expected: 3 tests FAIL with `AttributeError: 'AppSettings' object has no attribute 'schema_changes_max_batch_size'` (or `ImportError` if `tests/__init__.py` doesn't exist — should already exist, but check).

- [ ] **Step 3: Add `_int_env` helper and the new field**

In `src/py/novamoc/config.py`, after the `_float_env` function add:

```python
def _int_env(name: str, default: int) -> Callable[[], int]:
    """Build a ``default_factory`` that reads ``name`` from env and parses as int.

    A non-integer value raises ``ValueError`` at startup rather than
    silently falling through to the default.
    """

    def _read() -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            msg = f"cannot parse {raw!r} as int for {name}"
            raise ValueError(msg) from exc

    return _read
```

In the `AppSettings` dataclass, add a new field after `hlc_drift_limit_seconds`:

```python
    schema_changes_max_batch_size: int = field(
        default_factory=_int_env("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", 500)
    )
```

Update the `AppSettings` docstring `Attributes` block to mention the new field:

```
        schema_changes_max_batch_size: Upper bound on rows returned
            by a single ``GET /schema/changes`` page (M2.2). Clients
            page via ``next_since`` / ``has_more``.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): add schema_changes_max_batch_size to AppSettings

Surfaces the GET /schema/changes page-size cap as a tunable env var
(NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE, default 500). New _int_env
helper mirrors _float_env for early failure on junk values.
EOF
)"
```

---

## Task 2: Add `list_changes_after` to `SchemaChangeLogService`

**Files:**
- Modify: `src/py/novamoc/domain/schema/services/_change_log.py`
- Test: `tests/schema/test_changes_service.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/schema/test_changes_service.py`:

```python
"""Service-level tests for SchemaChangeLogService.list_changes_after."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(svc: SchemaChangeLogService, n: int) -> None:
    for _ in range(n):
        await svc.append(
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={"name": f"name-{_}"},
        )


async def test_list_changes_after_returns_rows_above_since(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=2, limit=100)
    seqs = [r.seq for r in rows]
    assert seqs == [3, 4, 5]


async def test_list_changes_after_respects_limit(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=0, limit=2)
    seqs = [r.seq for r in rows]
    assert seqs == [1, 2]


async def test_list_changes_after_orders_by_seq_ascending(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=0, limit=100)
    seqs = [r.seq for r in rows]
    assert seqs == sorted(seqs)
    assert seqs == [1, 2, 3, 4, 5]


async def test_list_changes_after_since_at_or_above_max_returns_empty(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 3)
    await session.flush()

    rows_at = await svc.list_changes_after(since=3, limit=100)
    rows_above = await svc.list_changes_after(since=99, limit=100)
    assert list(rows_at) == []
    assert list(rows_above) == []


async def test_list_changes_after_empty_tenant_returns_empty(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    rows = await svc.list_changes_after(since=0, limit=100)
    assert list(rows) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/schema/test_changes_service.py -v`

Expected: 5 tests FAIL with `AttributeError: 'SchemaChangeLogService' object has no attribute 'list_changes_after'`.

- [ ] **Step 3: Add the method**

In `src/py/novamoc/domain/schema/services/_change_log.py`:

Update the top-of-file `from typing import ...` block to include `Sequence`:

```python
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
```

At the end of the class body (after `current_version`), add:

```python
    async def list_changes_after(
        self,
        *,
        since: int,
        limit: int,
    ) -> Sequence[m.schema.SchemaChangeLog]:
        """Return rows with ``seq > since``, ascending by ``seq``, capped at ``limit``.

        Tenant scoping is supplied by Layer 1 of ``db._listeners``: this is
        an ORM ``select(SchemaChangeLog)`` so ``state.all_mappers`` is
        non-empty and ``with_loader_criteria`` attaches the predicate
        automatically. No ``tenant_id`` filter is added here.
        """
        stmt = (
            select(m.schema.SchemaChangeLog)
            .where(m.schema.SchemaChangeLog.seq > since)
            .order_by(m.schema.SchemaChangeLog.seq)
            .limit(limit)
        )
        result = await self.repository.session.execute(stmt)
        return result.scalars().all()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/schema/test_changes_service.py -v`

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/services/_change_log.py tests/schema/test_changes_service.py
git commit -m "$(cat <<'EOF'
feat(schema): add list_changes_after to SchemaChangeLogService

Returns schema_change_log rows with seq > since, ordered ascending,
bounded by limit. Tenant scoping comes from Layer 1's ORM path.
The page query for GET /schema/changes (issue #32) builds on this.
EOF
)"
```

---

## Task 3: Add cross-tenant isolation test for `list_changes_after`

**Files:**
- Modify: `tests/schema/test_cross_tenant_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/schema/test_cross_tenant_isolation.py`:

```python
@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_list_changes_after_returns_only_own_rows(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    """list_changes_after under a tenant must not leak sibling-tenant rows.

    ACTIVE_TRUCK seeds change-log rows under both t-a and t-b with overlapping
    seq ranges (each tenant sees its own dense 1, 2, 3, ...). The contextvar
    is what scopes the call to a single tenant's rows.
    """
    with use_tenant(tenant):
        rows = await services.change_log.list_changes_after(since=0, limit=100)
    assert all(r.tenant_id == tenant for r in rows)
    assert len(rows) > 0
```

- [ ] **Step 2: Run test to verify it passes (NOT fails)**

The Layer 1 listener already enforces this — we expect this test to pass on the first run, proving the structural enforcement is doing its job.

Run: `uv run pytest tests/schema/test_cross_tenant_isolation.py::test_list_changes_after_returns_only_own_rows -v`

Expected: PASS for both `t-a` and `t-b`.

If it fails: investigate before continuing. The new method should not need any per-call tenant filtering — Layer 1 must do it for us.

- [ ] **Step 3: Commit**

```bash
git add tests/schema/test_cross_tenant_isolation.py
git commit -m "$(cat <<'EOF'
test(schema): cover list_changes_after in cross-tenant isolation suite

Asserts the Layer 1 listener scopes the new query — no per-call
tenant_id is passed; the contextvar drives the WHERE clause.
EOF
)"
```

---

## Task 4: Add `SchemaChangeView` and `SchemaChangesResponse` to `_read_payloads.py`

**Files:**
- Modify: `src/py/novamoc/domain/schema/_read_payloads.py`

This task adds the wire-format Structs without exercising them. Their behaviour is covered by the E2E tests in Task 5. No dedicated test here.

- [ ] **Step 1: Add the new Structs**

Edit `src/py/novamoc/domain/schema/_read_payloads.py`. Update imports to add `datetime`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec

from novamoc.db.models.schema import FieldDataType
```

Append after `SchemaSnapshotResponse`:

```python
class SchemaChangeView(msgspec.Struct):
    """One row of the schema_change_log on the wire.

    ``payload`` is passed through from the JsonB column as-is — the read
    path does NOT round-trip through the command-side ``_payloads.py``
    structs. See the design spec for the rationale (rename-compatibility
    with historical rows; the payload was already validated at POST time).
    """

    seq: int
    command: str
    entity_id: UUID
    payload: dict[str, Any]
    committed_at: datetime
    actor_id: str | None


class SchemaChangesResponse(msgspec.Struct):
    """Wire envelope for ``GET /schema/changes``.

    ``schema_version`` is the tenant's current MAX(seq), read in the same
    transaction as ``changes`` so the pair is a single snapshot.
    ``next_since`` is the cursor the client passes back to continue paging
    (the last row's ``seq``, or the request's ``since`` when empty).
    ``has_more`` is true iff ``next_since < schema_version``.
    """

    schema_version: int
    changes: tuple[SchemaChangeView, ...]
    next_since: int
    has_more: bool
```

- [ ] **Step 2: Sanity check the module still imports**

Run: `uv run python -c "from novamoc.domain.schema._read_payloads import SchemaChangeView, SchemaChangesResponse; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/domain/schema/_read_payloads.py
git commit -m "$(cat <<'EOF'
feat(schema): add wire structs for GET /schema/changes

SchemaChangeView is one row of the change log; SchemaChangesResponse
is the envelope (schema_version, changes, next_since, has_more).
Both will be wired into SchemaController in the next task.
EOF
)"
```

---

## Task 5: Add `GET /schema/changes` handler with E2E coverage

**Files:**
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Test: `tests/schema/test_changes_endpoint_e2e.py` (create)

This task is the largest. Tests are written first (across one file) and then the handler is implemented to make them green.

- [ ] **Step 1: Write the failing E2E tests**

Create `tests/schema/test_changes_endpoint_e2e.py`:

```python
"""E2E HTTP tests for GET /schema/changes (issue #32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient

_TYPE_A = "11111111-1111-1111-1111-111111111111"
_TYPE_B = "22222222-2222-2222-2222-222222222222"
_TYPE_C = "33333333-3333-3333-3333-333333333333"


async def _seed_three_creates(client: AsyncTestClient) -> None:
    for eid, name in ((_TYPE_A, "A"), (_TYPE_B, "B"), (_TYPE_C, "C")):
        resp = await client.post(
            "/schema",
            json={
                "type": "create_asset_type",
                "entity_id": eid,
                "payload": {"name": name},
            },
        )
        assert resp.status_code in (200, 201), resp.text


async def test_empty_tenant_returns_empty_changes(client) -> None:
    resp = await client.get("/schema/changes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "schema_version": 0,
        "changes": [],
        "next_since": 0,
        "has_more": False,
    }


async def test_since_zero_returns_full_history(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] == 3
    assert body["next_since"] == 3
    assert body["has_more"] is False
    seqs = [c["seq"] for c in body["changes"]]
    assert seqs == [1, 2, 3]
    commands = [c["command"] for c in body["changes"]]
    assert commands == ["create_asset_type"] * 3


async def test_since_at_current_returns_empty_not_error(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=3")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 3
    assert body["changes"] == []
    assert body["next_since"] == 3
    assert body["has_more"] is False


async def test_since_above_current_returns_empty_not_error(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=999")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 3
    assert body["changes"] == []
    # next_since echoes the input when no rows are returned, so a client
    # that keeps calling with the same cursor doesn't go backwards.
    assert body["next_since"] == 999
    assert body["has_more"] is False


async def test_since_skips_rows_below_or_equal(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=1")
    assert resp.status_code == 200
    body = resp.json()
    seqs = [c["seq"] for c in body["changes"]]
    # Exclusive lower bound: seq > 1, so [2, 3].
    assert seqs == [2, 3]
    assert body["next_since"] == 3
    assert body["has_more"] is False


async def test_limit_pages_results(client) -> None:
    await _seed_three_creates(client)

    page1 = await client.get("/schema/changes?since=0&limit=2")
    assert page1.status_code == 200
    body1 = page1.json()
    assert [c["seq"] for c in body1["changes"]] == [1, 2]
    assert body1["next_since"] == 2
    assert body1["has_more"] is True

    page2 = await client.get(
        f"/schema/changes?since={body1['next_since']}&limit=2"
    )
    assert page2.status_code == 200
    body2 = page2.json()
    assert [c["seq"] for c in body2["changes"]] == [3]
    assert body2["next_since"] == 3
    assert body2["has_more"] is False


async def test_row_carries_payload_and_actor_id_null(client) -> None:
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": _TYPE_A,
            "payload": {"name": "Truck"},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "payload": {
                "parent_id": _TYPE_A,
                "name": "VIN",
                "data_type": "text",
            },
        },
    )

    resp = await client.get("/schema/changes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["changes"]) == 2

    create_type, create_field = body["changes"]
    assert create_type["command"] == "create_asset_type"
    assert create_type["entity_id"] == _TYPE_A
    assert create_type["payload"] == {"name": "Truck"}
    assert create_type["actor_id"] is None
    assert isinstance(create_type["committed_at"], str)
    assert "T" in create_type["committed_at"]  # ISO-8601-ish

    assert create_field["command"] == "create_asset_type_field"
    assert create_field["payload"] == {
        "parent_id": _TYPE_A,
        "name": "VIN",
        "data_type": "text",
    }


async def test_deactivate_and_activate_surface_as_separate_rows(client) -> None:
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": _TYPE_A,
            "payload": {"name": "Truck"},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "entity_id": _TYPE_A,
            "payload": {},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "activate_asset_type",
            "entity_id": _TYPE_A,
            "payload": {},
        },
    )

    resp = await client.get("/schema/changes")
    body = resp.json()
    commands = [c["command"] for c in body["changes"]]
    assert commands == [
        "create_asset_type",
        "deactivate_asset_type",
        "activate_asset_type",
    ]


async def test_since_negative_returns_400(client) -> None:
    resp = await client.get("/schema/changes?since=-1")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_limit_zero_returns_400(client) -> None:
    resp = await client.get("/schema/changes?limit=0")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_limit_above_max_returns_400(client) -> None:
    # Default max is 500; pick something definitively above.
    resp = await client.get("/schema/changes?limit=1000000")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_non_integer_query_returns_400(client) -> None:
    resp = await client.get("/schema/changes?since=abc")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_without_authorization_returns_401(client) -> None:
    resp = await client.get("/schema/changes", headers={"Authorization": ""})
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/schema/test_changes_endpoint_e2e.py -v`

Expected: every test FAILs (route does not exist yet; 404 from Litestar or similar).

- [ ] **Step 3: Add the DI provider and the handler**

Edit `src/py/novamoc/domain/schema/controllers/_schema.py`.

**Imports.** The file currently has:

```python
from litestar import Controller, Request, Response, get, post
from litestar.datastructures import ETag
```

and imports `_read_payloads` Structs and `ProblemDetails` already. Three additions are needed:

1. Add `State` to the existing `litestar.datastructures` import (Litestar binds the annotation to the request state at runtime, mirroring `EventsController`'s usage):

   ```python
   from litestar.datastructures import (
       ETag,
       State,  # noqa: TC002  # runtime DI provider annotation
   )
   ```

2. Add `Provide` from `litestar.di`:

   ```python
   from litestar.di import Provide
   ```

3. Extend the `_read_payloads` import block to include the two new Structs, and add the `_errors` import:

   ```python
   from novamoc.domain._errors import ErrorCode, PayloadShapeError
   from novamoc.domain.schema._read_payloads import (
       AssetTypeFieldView,
       AssetTypeView,
       MaintenanceRecordTypeFieldView,
       MaintenanceRecordTypeView,
       SchemaChangesResponse,
       SchemaChangeView,
       SchemaSnapshotResponse,
   )
   ```

**Module docstring.** Extend the existing top-of-file docstring with a new paragraph after the `GET /schema` block, before the `POST /schema's apply_command` paragraph:

```
``GET /schema/changes`` streams ``schema_change_log`` rows with
``seq > since``, ordered ascending, bounded by a configurable batch
size. The same ``TenantContextMiddleware`` + Layer 1 listener path
supplies the tenant predicate. Bounds errors on ``since`` / ``limit``
render through the existing ``ProblemDetailsPlugin`` as
``invalid_payload_shape``.
```

**DI provider.** Add a module-level function after the imports and before `_matches_current_etag`:

```python
async def _provide_max_batch_size(state: State) -> int:
    return state.settings.app.schema_changes_max_batch_size
```

**Dependencies block.** Update `SchemaController.dependencies` to include the new provider as the first key:

```python
    dependencies = (
        {
            "max_batch_size": Provide(_provide_max_batch_size),
        }
        | providers.create_service_dependencies(
            _services.AssetTypeService, "asset_type_service"
        )
        | providers.create_service_dependencies(
            _services.AssetTypeFieldService,
            "asset_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeService,
            "maintenance_record_type_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeFieldService,
            "maintenance_record_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.SchemaChangeLogService,
            "schema_change_log_service",
        )
    )
```

Add `from litestar.di import Provide` to the litestar import block.

Add the handler method on `SchemaController` (after `read_snapshot`):

```python
    @get(
        "/changes",
        responses={
            200: ResponseSpec(
                SchemaChangesResponse,
                description="Page of schema change log rows for the active tenant",
            ),
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid since/limit query parameter",
                media_type="application/problem+json",
            ),
            401: ResponseSpec(
                ProblemDetails,
                description="Tenant could not be resolved from request",
                media_type="application/problem+json",
            ),
        },
    )
    async def read_changes(
        self,
        schema_change_log_service: _services.SchemaChangeLogService,
        max_batch_size: int,
        since: int = 0,
        limit: int | None = None,
    ) -> SchemaChangesResponse:
        # Range checks. INVALID_PAYLOAD_SHAPE is the existing code for
        # "the request couldn't be decoded against the expected shape" — see
        # the design spec. We do them here rather than via Parameter(ge=...,
        # le=...) because the upper bound is settings-derived and not a
        # literal at class-body parse time.
        if since < 0:
            raise PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message="since must be >= 0",
                field="since",
                received=since,
            )
        effective_limit = max_batch_size if limit is None else limit
        if effective_limit < 1 or effective_limit > max_batch_size:
            raise PayloadShapeError(
                code=ErrorCode.INVALID_PAYLOAD_SHAPE,
                message=(
                    f"limit must be between 1 and {max_batch_size} inclusive"
                ),
                field="limit",
                received=limit,
                max=max_batch_size,
            )

        # Snapshot consistency: schema_version and the page read share the
        # same request-scoped session, so they observe one WAL snapshot.
        # Read schema_version FIRST so a client never sees next_since >
        # schema_version (would mislead the has_more calculation).
        schema_version = await schema_change_log_service.current_version()
        rows = await schema_change_log_service.list_changes_after(
            since=since, limit=effective_limit
        )

        changes = tuple(
            SchemaChangeView(
                seq=r.seq,
                command=r.command,
                entity_id=r.entity_id,
                payload=r.payload,
                committed_at=r.committed_at,
                actor_id=r.actor_id,
            )
            for r in rows
        )
        next_since = changes[-1].seq if changes else since
        has_more = next_since < schema_version

        return SchemaChangesResponse(
            schema_version=schema_version,
            changes=changes,
            next_since=next_since,
            has_more=has_more,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/schema/test_changes_endpoint_e2e.py -v`

Expected: all 12 tests PASS.

If any fail, read the failure, fix the handler (not the test), re-run. Common likely failures:
- `PayloadShapeError` not caught by problem-details plugin → confirm `_problem_details.py` already covers `DomainError` subclasses (it does); the `DomainError` base in `_problem_details.exception_to_problem_detail_map` registration handles it by inheritance.
- Litestar 400 (instead of 200) on non-integer `since=abc` → that's expected via Litestar's own `ValidationException`, which is mapped to `invalid_payload_shape` by the existing converter.
- `committed_at` serialization shape — msgspec defaults to ISO-8601 strings for `datetime`; the test only checks for a string with `T` in it, so this should hold.

- [ ] **Step 5: Spot-check the full schema test suite still passes**

Run: `uv run pytest tests/schema/ -v`

Expected: every test PASSes (the existing schema/snapshot tests must be untouched).

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/controllers/_schema.py tests/schema/test_changes_endpoint_e2e.py
git commit -m "$(cat <<'EOF'
feat(schema): GET /schema/changes catch-up endpoint (#32)

Server side of ADR-009's catch-up flow: paged, transactionally
consistent stream of schema_change_log rows above a client-supplied
seq cursor. Echo cursor (next_since/has_more), batch size capped by
AppSettings.schema_changes_max_batch_size, payload passed through
as-is per the design spec.

Closes #32.
EOF
)"
```

---

## Task 6: Lint, format, type-check, and the full suite

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`

Expected: every test PASSes.

If a test fails: read the failure, fix at the root cause, do not skip or `xfail`.

- [ ] **Step 2: Lint**

Run: `uv run ruff check`

If any new violations appear in files we modified, follow CLAUDE.md's ruff workflow:
1. Read the rule (`uv run ruff rule <CODE>`).
2. Try `uv run ruff check --fix` (safe fixes only).
3. Fix manually if no safe autofix.
4. Module-level `# ruff: noqa: <CODE>` with rationale is the last resort.

Run the ratchet to ensure no count regressed:

```bash
uv run python scripts/ratchet.py
```

Expected: ratchet passes (no count above baseline). If a count *decreased*, run `just ratchet-update` and add the new baseline to the commit.

- [ ] **Step 3: Format**

Run: `uv run ruff format`

Expected: at most reformats whitespace; nothing semantically changes.

- [ ] **Step 4: Type-check**

Run: `uv run ty check`

Expected: zero errors.

- [ ] **Step 5: Commit any cleanup**

If steps 2–4 produced any changes, stage and commit them:

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(schema): lint/format/typecheck after #32

Trailing cleanup after adding the /schema/changes endpoint —
nothing semantic.
EOF
)"
```

If steps 2–4 produced no changes, skip this step.

- [ ] **Step 6: Run `just check` as the final gate**

Run: `just check`

Expected: every recipe (`lint`, `format`, `typecheck`, `test`) green.

If anything fails: fix and re-run before declaring done. Do not declare the task complete on a failing `just check`.

---

## Spec coverage check

The plan covers every acceptance criterion from the issue:

| Acceptance criterion | Covered by |
|---|---|
| New `GET /schema/changes?since=<seq>` route on `SchemaController` | Task 5 |
| Returns rows with `seq > since` ordered ascending | Task 2, Task 5 |
| Tenant resolved by `TenantContextMiddleware`; no tenant in URL/body | Task 5 (no tenant param), Task 3 (cross-tenant test) |
| `since=0` returns full history | Task 5 (`test_since_zero_returns_full_history`) |
| `since >= current_version` returns empty list, not an error | Task 5 (`test_since_at_current_returns_empty_not_error`, `test_since_above_current_returns_empty_not_error`) |
| Exclusive cursor semantics (`seq > since`) | Task 2, Task 5 (`test_since_skips_rows_below_or_equal`) |
| Bounded response with `next_since` / `has_more` | Task 4 (struct), Task 5 (handler + `test_limit_pages_results`) |
| Each row carries `seq`, `command`, `entity_id`, `payload`, `committed_at`, `actor_id` | Task 4, Task 5 (`test_row_carries_payload_and_actor_id_null`) |
| Wire shape in `_read_payloads.py`; types publishable in OpenAPI | Task 4, Task 5 (`responses=` block) |
| Errors render as `application/problem+json` per ADR-016 | Task 5 (range error tests, auth test) |
| Cross-tenant isolation test | Task 3 |
| E2E + service/handler-level tests | Task 2 (service), Task 5 (E2E) |
| `just check` green | Task 6 |
