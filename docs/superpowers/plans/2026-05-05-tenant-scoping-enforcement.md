# Tenant Scoping Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tenant scoping a structural property of the storage layer — auto-inject `tenant_id` predicates on ORM SELECTs, auto-stamp `tenant_id` on ORM INSERTs, and reject any tenant-scoped DML that escapes those layers without a `tenant_id` predicate. Resolves issue [#51](https://github.com/shoriminimoe/novamoc/issues/51).

**Architecture:** Three SQLAlchemy event listeners (`do_orm_execute` for reads, `before_flush` for ORM inserts, `before_execute` as a Core-DML backstop) keyed off a `current_tenant_id` ContextVar. The contextvar is set by a new `TenantContextMiddleware` that stacks after the existing `AuthenticationMiddleware`. A `TenantScopedMixin` (column-only) replaces `TenantScopedAuditBase`; tables compose it with whichever advanced-alchemy base/mixin matches their PK and audit needs. Listeners identify "tenant-scoped table" by column presence (`tenant_id in __table__.columns`), not class hierarchy.

**Tech Stack:** Python 3.14, Litestar, advanced-alchemy / SQLAlchemy 2.x async, aiosqlite, msgspec, pytest (asyncio auto mode), uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-05-05-tenant-scoping-enforcement-design.md`

---

## File Map

**New files**

- `src/py/novamoc/db/_errors.py` — `UnscopedQueryError`, `CrossTenantWriteError`.
- `src/py/novamoc/db/_tenant_context.py` — `current_tenant_id` ContextVar, `SKIP_TENANT_FILTER` exec-option key, `use_tenant` context manager.
- `src/py/novamoc/db/models/_mixins.py` — `TenantScopedMixin`.
- `src/py/novamoc/db/_listeners.py` — Layer 1 / 2 / 3 listeners.
- `tests/db/__init__.py`
- `tests/db/test_tenant_context.py`
- `tests/db/test_layer1_loader_criteria.py`
- `tests/db/test_layer2_before_flush.py`
- `tests/db/test_layer3_before_execute.py`
- `tests/db/test_listener_wiring.py`
- `tests/accounts/test_tenant_context_middleware.py`
- `tests/schema/test_cross_tenant_isolation.py`

**Edited files**

- `src/py/novamoc/db/models/_base.py` — delete `TenantScopedAuditBase`.
- `src/py/novamoc/db/models/schema/_asset_type.py` — switch base to `(TenantScopedMixin, UUIDAuditBase)`.
- `src/py/novamoc/db/models/schema/_maintenance_record_type.py` — same.
- `src/py/novamoc/db/models/schema/_change_log.py` — drop hand-declared `tenant_id`, add mixin.
- `src/py/novamoc/db/models/data/_asset.py` — switch projection base + mixin on `AssetFieldValue`.
- `src/py/novamoc/db/models/data/_maintenance_record.py` — same.
- `src/py/novamoc/db/models/data/_event.py` — gain mixin, composite PK, drop redundant index.
- `src/py/novamoc/asgi.py` — import `db._listeners` for side-effect; add `TenantContextMiddleware` to middleware stack.
- `src/py/novamoc/domain/accounts/_middleware.py` — add `TenantContextMiddleware`.
- `src/py/novamoc/domain/accounts/__init__.py` — re-export `TenantContextMiddleware`.
- `src/py/novamoc/domain/schema/_handlers/asset_type.py` — drop `tenant_id=auth.tenant_id` from reads, drop `"tenant_id"` from create dicts.
- `src/py/novamoc/domain/schema/_handlers/asset_type_field.py` — same.
- `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py` — same.
- `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py` — same.
- `src/py/novamoc/domain/schema/services/_asset_type.py` — collapse `list_for_tenant`.
- `src/py/novamoc/domain/schema/services/_asset_type_field.py` — same.
- `src/py/novamoc/domain/schema/services/_maintenance_record_type.py` — same.
- `src/py/novamoc/domain/schema/services/_maintenance_record_type_field.py` — same.
- `src/py/novamoc/domain/schema/services/_change_log.py` — drop `tenant_id` arg from `append`/`current_version`.
- `src/py/novamoc/domain/schema/controllers/_schema.py` — adopt new service signatures, push `OrderBy` ordering into the read controller.
- `tests/conftest.py` — import `db._listeners`; provide `tenant` fixture; seed sets contextvar.
- `tests/data/loader.py` — accept `tenant_id` override (sets contextvar around the load).
- `tests/data/fixtures/truck/asset_type.json` — drop hardcoded `tenant_id` (auto-stamped instead).
- `tests/data/fixtures/truck/asset_type__deactivated.json` — same.
- `tests/data/fixtures/truck/asset_type_field__vin.json` — same.
- `tests/data/scenarios.py` — append a `TWO_TENANT_TRUCK` scenario for the cross-tenant test (Task 15).

---

## Task 1: `db/_errors.py` — typed exceptions

**Files:**
- Create: `src/py/novamoc/db/_errors.py`
- Test: (no separate test file — exception classes are exercised by listener tests)

- [ ] **Step 1: Implement the module**

```python
# src/py/novamoc/db/_errors.py
"""Programming-error exceptions raised by the tenant-scoping listeners.

These are not user-facing failures and do not get problem-details
renderers — the storage layer raises them when a tenant-scoped table
is touched without a tenant scope or when a write disagrees with the
current tenant context. Handlers must not catch them; they propagate
to a 500 from the framework so the bug is visible in CI/dev.
"""

from __future__ import annotations


class UnscopedQueryError(RuntimeError):
    """A statement against a tenant-scoped table executed without a tenant scope."""


class CrossTenantWriteError(RuntimeError):
    """An ORM instance was flushed with a tenant_id different from the contextvar."""
```

- [ ] **Step 2: Run lint + typecheck**

Run: `just lint-py && just typecheck-py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/db/_errors.py
git commit -m "feat(db): add UnscopedQueryError + CrossTenantWriteError"
```

---

## Task 2: `db/_tenant_context.py` — ContextVar + use_tenant helper

**Files:**
- Create: `src/py/novamoc/db/_tenant_context.py`
- Test: `tests/db/test_tenant_context.py`
- Create: `tests/db/__init__.py`

- [ ] **Step 1: Create `tests/db/__init__.py`**

Empty file.

```bash
mkdir -p tests/db
: > tests/db/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/db/test_tenant_context.py
from __future__ import annotations

import pytest

from novamoc.db._tenant_context import current_tenant_id, use_tenant


def test_default_is_none() -> None:
    assert current_tenant_id.get() is None


def test_use_tenant_sets_and_resets() -> None:
    assert current_tenant_id.get() is None
    with use_tenant("t-a"):
        assert current_tenant_id.get() == "t-a"
    assert current_tenant_id.get() is None


def test_use_tenant_nested() -> None:
    with use_tenant("t-a"):
        with use_tenant("t-b"):
            assert current_tenant_id.get() == "t-b"
        assert current_tenant_id.get() == "t-a"
    assert current_tenant_id.get() is None


def test_use_tenant_resets_on_exception() -> None:
    with pytest.raises(ValueError):
        with use_tenant("t-a"):
            assert current_tenant_id.get() == "t-a"
            raise ValueError("boom")
    assert current_tenant_id.get() is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/db/test_tenant_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novamoc.db._tenant_context'`

- [ ] **Step 4: Implement the module**

```python
# src/py/novamoc/db/_tenant_context.py
"""Per-request tenant context.

The ContextVar is set by `TenantContextMiddleware` for every HTTP
request after credential resolution. Tests and scripts that need to
exercise the storage layer outside the HTTP lifecycle use the
`use_tenant` context manager.

`SKIP_TENANT_FILTER` is the execution-option key that suppresses
Layer 1's loader-criteria injection and Layer 3's WHERE/VALUES
backstop. Layer 2's auto-stamp behaviour is unaffected by it. Used
only by deliberate cross-tenant administrative operations; v1 has no
production callers.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

current_tenant_id: ContextVar[str | None] = ContextVar(
    "novamoc_current_tenant_id", default=None
)

SKIP_TENANT_FILTER = "novamoc_skip_tenant_filter"


@contextmanager
def use_tenant(tenant_id: str) -> Iterator[None]:
    """Set the tenant context for the duration of the with-block.

    Resets to the prior value (including None) on exit, even if the
    block raises.
    """
    token = current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/db/test_tenant_context.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/_tenant_context.py tests/db/__init__.py tests/db/test_tenant_context.py
git commit -m "feat(db): add current_tenant_id contextvar + use_tenant helper"
```

---

## Task 3: `db/models/_mixins.py` — TenantScopedMixin

**Files:**
- Create: `src/py/novamoc/db/models/_mixins.py`
- Test: (regression-tested by Task 4's model refactor; no standalone test)

- [ ] **Step 1: Implement the mixin**

```python
# src/py/novamoc/db/models/_mixins.py
"""Reusable declarative mixins for db models.

This module is intentionally not scoped to tenancy in its name —
future mixins (timestamping flavours, soft-delete, etc.) belong here
alongside ``TenantScopedMixin``.
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column


class TenantScopedMixin:
    """Mark a mapped class as tenant-scoped.

    Adds ``tenant_id`` as a primary-key column with ``sort_order=-200``,
    so when composed with a UUID/BigInt PK base the composite PK leads
    with ``tenant_id`` (ADR-014). Targeted by the three enforcement
    listeners in ``db/_listeners.py``, which identify "tenant-scoped
    table" by column presence rather than this class.
    """

    tenant_id: Mapped[str] = mapped_column(primary_key=True, sort_order=-200)
```

- [ ] **Step 2: Lint + typecheck**

Run: `just lint-py && just typecheck-py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/db/models/_mixins.py
git commit -m "feat(db): add TenantScopedMixin"
```

---

## Task 4: Refactor projection-table models to use `TenantScopedMixin`

**Files:**
- Modify: `src/py/novamoc/db/models/_base.py`
- Modify: `src/py/novamoc/db/models/schema/_asset_type.py`
- Modify: `src/py/novamoc/db/models/schema/_maintenance_record_type.py`
- Modify: `src/py/novamoc/db/models/data/_asset.py`
- Modify: `src/py/novamoc/db/models/data/_maintenance_record.py`

The existing test suite is the regression net for this refactor — no new tests.

- [ ] **Step 1: Replace `_base.py` contents (delete `TenantScopedAuditBase`)**

The file currently defines only `TenantScopedAuditBase`. Empty the file (or delete it entirely if nothing else lives there). Per CLAUDE.md, don't introduce comment-shaped placeholders.

```bash
git rm src/py/novamoc/db/models/_base.py
```

- [ ] **Step 2: Update `db/models/schema/_asset_type.py`**

Replace the existing imports and `AssetType` / `AssetTypeField` definitions to use the mixin and `UUIDAuditBase`. (Read the file with the Read tool first; replace `TenantScopedAuditBase` references with `(TenantScopedMixin, UUIDAuditBase)` composition.)

```python
# src/py/novamoc/db/models/schema/_asset_type.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import GUID, JsonB
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from novamoc.db.models._mixins import TenantScopedMixin


class AssetType(TenantScopedMixin, UUIDAuditBase):
    __tablename__ = "asset_types"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_asset_types_tenant_name"),)

    name: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="1")


class AssetTypeField(TenantScopedMixin, UUIDAuditBase):
    __tablename__ = "asset_type_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["asset_types.tenant_id", "asset_types.id"],
        ),
        UniqueConstraint(
            "tenant_id", "parent_id", "name", name="uq_asset_type_fields_tenant_parent_name"
        ),
    )

    parent_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str]
    data_type: Mapped[str]
    validation: Mapped[dict[str, Any] | None] = mapped_column(JsonB)
    active: Mapped[bool] = mapped_column(default=True, server_default="1")
```

(The exact column set must match the file you replace — read first to preserve any field this draft missed. The pattern is "remove `from .._base import TenantScopedAuditBase`, add `from novamoc.db.models._mixins import TenantScopedMixin`, change `class X(TenantScopedAuditBase)` to `class X(TenantScopedMixin, UUIDAuditBase)`".)

- [ ] **Step 3: Same edit on `_maintenance_record_type.py`**

Apply the same pattern to `MaintenanceRecordType` and `MaintenanceRecordTypeField`.

- [ ] **Step 4: Update `data/_asset.py`**

`Asset` switches to `(TenantScopedMixin, UUIDAuditBase)`. Read the file first to preserve column declarations.

```python
class Asset(TenantScopedMixin, UUIDAuditBase):
    __tablename__ = "assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["asset_types.tenant_id", "asset_types.id"],
        ),
    )

    type_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str | None]
    properties: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict, server_default="{}")
    deleted: Mapped[bool] = mapped_column(default=False, server_default="0")
    row_state_hlc: Mapped[str]
```

`AssetFieldValue` (in the same file) drops its hand-declared `tenant_id` and inherits from `(TenantScopedMixin, DefaultBase)`:

```python
class AssetFieldValue(TenantScopedMixin, DefaultBase):
    __tablename__ = "asset_field_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    field_id: Mapped[str] = mapped_column(primary_key=True)
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    hlc: Mapped[str]
```

- [ ] **Step 5: Update `data/_maintenance_record.py`**

Same pattern for `MaintenanceRecord` and `MaintenanceRecordFieldValue`.

- [ ] **Step 6: Drop the `_base` import from `db/models/__init__.py`**

```bash
grep -n "_base" src/py/novamoc/db/models/__init__.py
```

If anything imports from `._base`, remove that import.

- [ ] **Step 7: Run tests + typecheck**

Run: `just typecheck-py && just test-py`
Expected: PASS — schema endpoint tests run unchanged because the resulting tables have the same columns and PKs. (If failures appear, the most likely cause is a missing column in the model rewrite — re-read the original and add what's missing.)

- [ ] **Step 8: Commit**

```bash
git add -A src/py/novamoc/db/models/
git commit -m "refactor(db): use TenantScopedMixin in projection tables"
```

---

## Task 5: Refactor `SchemaChangeLog` to use the mixin

**Files:**
- Modify: `src/py/novamoc/db/models/schema/_change_log.py`

- [ ] **Step 1: Replace the model definition**

```python
# src/py/novamoc/db/models/schema/_change_log.py
from __future__ import annotations

import datetime as _dt
from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import DateTimeUTC, GUID, JsonB
from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from novamoc.db.models._mixins import TenantScopedMixin


class SchemaChangeLog(TenantScopedMixin, DefaultBase):
    """Append-only audit log of accepted schema commands (ADR-008).

    Composite PK ``(tenant_id, seq)`` — ``tenant_id`` from the mixin,
    ``seq`` declared here. Per-tenant dense ``1, 2, 3, …`` sequence;
    ``seq`` is application-managed (next_seq is computed at insert
    time in ``SchemaChangeLogService.append``), distinguishing this
    table from ``EventLog`` whose ``seq`` is DB-managed and globally
    monotonic.
    """

    __tablename__ = "schema_change_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    command: Mapped[str]
    entity_id: Mapped[UUID] = mapped_column(GUID)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB)
    committed_at: Mapped[_dt.datetime] = mapped_column(
        DateTimeUTC,
        server_default=func.now(),
        default=lambda: _dt.datetime.now(_dt.timezone.utc),
    )
    actor_id: Mapped[str | None]
```

- [ ] **Step 2: Run tests + typecheck**

Run: `just typecheck-py && just test-py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/db/models/schema/_change_log.py
git commit -m "refactor(db): use TenantScopedMixin in SchemaChangeLog"
```

---

## Task 6: `EventLog` — keep today's shape (SQLite blocks composite-PK + autoincrement)

**Files:**
- (none — model unchanged)

**Outcome.** During implementation, attempting `class EventLog(TenantScopedMixin, DefaultBase)` failed at DDL-emit time with `sqlalchemy.exc.CompileError: SQLite does not support autoincrement for composite primary keys`. SQLite's `INTEGER PRIMARY KEY AUTOINCREMENT` optimization is only legal on a sole-column INTEGER PK. ADR-011 requires `seq` to be globally monotonic, which depends on the autoincrement guarantee, so the composite PK approach is incompatible with SQLite for this table.

The fallback (already documented in the spec) is taken: **`EventLog` keeps today's shape**. No model change, no new test. The hand-declared `tenant_id` column on `EventLog` is still picked up by all three enforcement listeners' column-presence heuristic (see Tasks 7–9), so EventLog gets the same protection as every other tenant-scoped table — the mixin is convenience, not enforcement.

The spec is updated in the same commit to record this deviation.

- [ ] **Step 1: Verify `EventLog` model is unchanged**

```bash
git diff f9873ab..HEAD -- src/py/novamoc/db/models/data/_event.py
```

Expected: empty diff (no changes since Task 5).

- [ ] **Step 2: Update the spec to record the deviation**

Edit `docs/superpowers/specs/2026-05-05-tenant-scoping-enforcement-design.md`:

- In the Components composition table, change `EventLog`'s row to: `DefaultBase` + hand-declared `tenant_id: Mapped[str]` (non-PK), sole `seq` PK; resulting PK `seq` (sole).
- Replace the *EventLog vs SchemaChangeLog* explanation with a note that `EventLog` is the one synced table that does NOT inherit the mixin (because of SQLite's DDL constraint), and that it stays at today's shape with the hand-declared `tenant_id`, sole `seq` PK, and the `idx_event_log_tenant_seq` explicit index.
- In the Migration notes, change the `EventLog` bullet to "unchanged — see EventLog deviation in Components above".

- [ ] **Step 3: Run tests + typecheck**

Run: `just typecheck-py && just test-py`
Expected: PASS (no behaviour change).

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-05-tenant-scoping-enforcement-design.md
git commit -m "docs(spec): EventLog deviation — sole seq PK retained (SQLite limitation)"
```

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/db/models/data/_event.py tests/db/test_event_log_seq_monotonic.py
git commit -m "refactor(db): EventLog uses TenantScopedMixin with composite PK"
```

---

## Task 7: Layer 2 — `before_flush` listener (auto-stamp + cross-tenant check)

**Files:**
- Create: `src/py/novamoc/db/_listeners.py` (just Layer 2 in this task)
- Test: `tests/db/test_layer2_before_flush.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_layer2_before_flush.py
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import novamoc.db._listeners  # noqa: F401  -- registers listeners on import
from novamoc.db._errors import CrossTenantWriteError, UnscopedQueryError
from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.schema._asset_type import AssetType


@pytest.mark.asyncio
async def test_stamps_tenant_id_on_new_instance(session: AsyncSession) -> None:
    obj = AssetType(name="Truck", active=True)
    with use_tenant("t-a"):
        session.add(obj)
        await session.flush()
    assert obj.tenant_id == "t-a"


@pytest.mark.asyncio
async def test_keeps_explicit_tenant_id_when_matching_context(session: AsyncSession) -> None:
    obj = AssetType(tenant_id="t-a", name="Truck", active=True)
    with use_tenant("t-a"):
        session.add(obj)
        await session.flush()
    assert obj.tenant_id == "t-a"


@pytest.mark.asyncio
async def test_raises_when_no_context_and_no_tenant_id(session: AsyncSession) -> None:
    obj = AssetType(name="Truck", active=True)
    session.add(obj)
    with pytest.raises(UnscopedQueryError):
        await session.flush()


@pytest.mark.asyncio
async def test_raises_on_cross_tenant_write(session: AsyncSession) -> None:
    obj = AssetType(tenant_id="t-b", name="Truck", active=True)
    with use_tenant("t-a"):
        session.add(obj)
        with pytest.raises(CrossTenantWriteError):
            await session.flush()


@pytest.mark.asyncio
async def test_ignores_non_tenant_scoped_models(session: AsyncSession) -> None:
    """Models without tenant_id columns aren't touched by the listener."""
    # No-op: there are currently no non-tenant-scoped mapped classes
    # in this codebase. Placeholder for when one is added.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_layer2_before_flush.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novamoc.db._listeners'`.

- [ ] **Step 3: Implement Layer 2**

```python
# src/py/novamoc/db/_listeners.py
"""Tenant-scoping enforcement listeners (issue #51).

Three layers, registered at import time on SQLAlchemy's global event
system. Importing this module is the entire wiring step — see
asgi.create_app and tests/conftest.py.

Layer 1: do_orm_execute injects a tenant_id WHERE predicate on every
ORM SELECT against a class with a tenant_id column.
Layer 2: before_flush stamps tenant_id on new ORM instances of
tenant-scoped models, and rejects cross-tenant writes.
Layer 3: before_execute is the backstop for Core-level INSERT /
UPDATE / DELETE that bypasses Layers 1-2.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from novamoc.db._errors import CrossTenantWriteError, UnscopedQueryError
from novamoc.db._tenant_context import current_tenant_id


def _is_tenant_scoped(table) -> bool:
    return "tenant_id" in table.columns


def _instance_is_tenant_scoped(obj: object) -> bool:
    table = getattr(obj, "__table__", None)
    return table is not None and _is_tenant_scoped(table)


@event.listens_for(Session, "before_flush")
def _stamp_or_reject_tenant(session, flush_context, instances) -> None:
    tid = current_tenant_id.get()
    for obj in session.new:
        if not _instance_is_tenant_scoped(obj):
            continue
        if obj.tenant_id is None:
            if tid is None:
                raise UnscopedQueryError(
                    f"Tenant-scoped INSERT attempted without tenant context: "
                    f"{type(obj).__name__}"
                )
            obj.tenant_id = tid
        elif tid is not None and obj.tenant_id != tid:
            raise CrossTenantWriteError(
                f"INSERT into {type(obj).__name__} for tenant {obj.tenant_id} "
                f"under context {tid}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/db/test_layer2_before_flush.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `just test-py`
Expected: existing tests still pass — the auto-stamp is additive (existing fixtures pass `tenant_id` explicitly, which agrees with whatever contextvar a test sets, or with no contextvar set the old code keeps working — actually wait: tests that don't set a contextvar AND seed via the existing JSON fixtures will pass `tenant_id="t1"` explicitly, which under "no contextvar set" goes through the auto-stamp branch's `tid is not None and obj.tenant_id != tid` check. That branch's guard is `tid is not None`, so when `tid is None`, no check runs. Pass. ✓)

If anything fails: most likely a test triggers a flush without setting the contextvar AND without explicit tenant_id. Add the contextvar in that test or fixture. Diagnose then proceed.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/_listeners.py tests/db/test_layer2_before_flush.py
git commit -m "feat(db): Layer 2 — before_flush auto-stamps tenant_id (issue #51)"
```

---

## Task 8: Layer 1 — `do_orm_execute` listener (loader criteria + fail closed)

**Files:**
- Modify: `src/py/novamoc/db/_listeners.py`
- Test: `tests/db/test_layer1_loader_criteria.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_layer1_loader_criteria.py
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import novamoc.db._listeners  # noqa: F401
from novamoc.db._errors import UnscopedQueryError
from novamoc.db._tenant_context import SKIP_TENANT_FILTER, use_tenant
from novamoc.db.models.schema._asset_type import AssetType


async def _seed_two_tenants(session: AsyncSession) -> None:
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    with use_tenant("t-b"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()


@pytest.mark.asyncio
async def test_select_under_tenant_returns_only_own_rows(session: AsyncSession) -> None:
    await _seed_two_tenants(session)
    with use_tenant("t-a"):
        result = (await session.execute(select(AssetType))).scalars().all()
    assert {row.tenant_id for row in result} == {"t-a"}


@pytest.mark.asyncio
async def test_select_without_context_raises(session: AsyncSession) -> None:
    await _seed_two_tenants(session)
    # No contextvar set
    with pytest.raises(UnscopedQueryError):
        (await session.execute(select(AssetType))).scalars().all()


@pytest.mark.asyncio
async def test_skip_tenant_filter_disables_layer1(session: AsyncSession) -> None:
    await _seed_two_tenants(session)
    # Cross-tenant administrative read.
    result = (
        await session.execute(
            select(AssetType).execution_options(**{SKIP_TENANT_FILTER: True})
        )
    ).scalars().all()
    assert {row.tenant_id for row in result} == {"t-a", "t-b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_layer1_loader_criteria.py -v`
Expected: FAIL — first test returns rows from both tenants; second test returns rows instead of raising; third may pass coincidentally.

- [ ] **Step 3: Add Layer 1 to `_listeners.py`**

Append to the existing `_listeners.py`:

```python
from sqlalchemy.orm import with_loader_criteria


def _build_tenant_predicate(cls):
    tid = current_tenant_id.get()
    if tid is None:
        raise UnscopedQueryError(
            f"Tenant-scoped SELECT against {cls.__name__} attempted "
            f"without tenant context"
        )
    return cls.tenant_id == tid


@event.listens_for(Session, "do_orm_execute")
def _inject_tenant_filter(state) -> None:
    if not state.is_select:
        return
    if state.execution_options.get("novamoc_skip_tenant_filter"):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            lambda cls: "tenant_id" in cls.__table__.columns,
            _build_tenant_predicate,
            include_aliases=True,
        )
    )
```

(Note: the `state.execution_options` key is the literal string from `SKIP_TENANT_FILTER` — using the constant requires importing it; the literal is acceptable here because the constant lives in the same package and the value is stable. Prefer the constant if the import doesn't create a cycle.)

- [ ] **Step 4: Run Layer 1 tests to verify they pass**

Run: `uv run pytest tests/db/test_layer1_loader_criteria.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Run Layer 2 + full suite**

Run: `uv run pytest tests/db/ -v && just test-py`
Expected: All tests still pass. The existing schema-endpoint E2E tests run *without* the contextvar set today, so they'll fail at the SELECT step with `UnscopedQueryError` — this is expected and is fixed in Task 11 (the middleware) and Task 14 (the conftest seed fixture). Stop here; the failures are progress, not regressions.

> If you want a green run before continuing, temporarily set the contextvar in `tests/conftest.py`'s `services` fixture to `"t1"`. That makes the suite green and is a good intermediate state. Otherwise proceed to Task 9.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/_listeners.py tests/db/test_layer1_loader_criteria.py
git commit -m "feat(db): Layer 1 — do_orm_execute injects tenant_id predicate (issue #51)"
```

---

## Task 9: Layer 3 — `before_execute` backstop (Core DML)

**Files:**
- Modify: `src/py/novamoc/db/_listeners.py`
- Test: `tests/db/test_layer3_before_execute.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_layer3_before_execute.py
from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

import novamoc.db._listeners  # noqa: F401
from novamoc.db._errors import UnscopedQueryError
from novamoc.db._tenant_context import SKIP_TENANT_FILTER, use_tenant
from novamoc.db.models.schema._asset_type import AssetType


@pytest.mark.asyncio
async def test_core_insert_without_tenant_raises(session: AsyncSession) -> None:
    stmt = insert(AssetType).values(id="00000000-0000-0000-0000-000000000001", name="X", active=True)
    with use_tenant("t-a"):
        with pytest.raises(UnscopedQueryError):
            await session.execute(stmt)


@pytest.mark.asyncio
async def test_core_update_without_tenant_predicate_raises(session: AsyncSession) -> None:
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = update(AssetType).values(name="Lorry").where(AssetType.name == "Truck")
    with use_tenant("t-a"):
        with pytest.raises(UnscopedQueryError):
            await session.execute(stmt)


@pytest.mark.asyncio
async def test_core_delete_without_tenant_predicate_raises(session: AsyncSession) -> None:
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = delete(AssetType).where(AssetType.name == "Truck")
    with use_tenant("t-a"):
        with pytest.raises(UnscopedQueryError):
            await session.execute(stmt)


@pytest.mark.asyncio
async def test_core_update_with_tenant_predicate_passes(session: AsyncSession) -> None:
    with use_tenant("t-a"):
        session.add(AssetType(name="Truck", active=True))
        await session.flush()
    stmt = (
        update(AssetType)
        .values(name="Lorry")
        .where(AssetType.tenant_id == "t-a", AssetType.name == "Truck")
    )
    with use_tenant("t-a"):
        await session.execute(stmt)  # no raise


@pytest.mark.asyncio
async def test_skip_tenant_filter_disables_layer3(session: AsyncSession) -> None:
    stmt = (
        update(AssetType)
        .values(name="Y")
        .where(AssetType.name == "Z")
        .execution_options(**{SKIP_TENANT_FILTER: True})
    )
    with use_tenant("t-a"):
        await session.execute(stmt)  # no raise even though no tenant_id predicate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_layer3_before_execute.py -v`
Expected: FAIL — Core DML executes without raising.

- [ ] **Step 3: Implement Layer 3**

Append to `_listeners.py`:

```python
from sqlalchemy import Delete, Engine, Insert, Update
from sqlalchemy.sql.elements import BinaryExpression


def _values_carries_tenant(insert_stmt, params) -> bool:
    """Return True if the INSERT statement names tenant_id in its values."""
    compiled = insert_stmt.compile()
    if "tenant_id" in compiled.params:
        return True
    multi_values = getattr(insert_stmt, "_multi_values", ()) or ()
    for row in multi_values:
        for col, _ in row:
            if getattr(col, "name", None) == "tenant_id":
                return True
    explicit = insert_stmt._values  # SQLAlchemy 2.x internal — values dict
    if explicit and "tenant_id" in {
        getattr(c, "name", c) for c in explicit
    }:
        return True
    if isinstance(params, dict) and "tenant_id" in params:
        return True
    if isinstance(params, (list, tuple)):
        return any(isinstance(p, dict) and "tenant_id" in p for p in params)
    return False


def _whereclause_filters_tenant(stmt) -> bool:
    """Return True iff the WHERE tree contains a comparison referencing
    a tenant_id column on a tenant-scoped table.
    """
    where = stmt.whereclause
    if where is None:
        return False
    return _walk_for_tenant(where)


def _walk_for_tenant(elem) -> bool:
    if isinstance(elem, BinaryExpression):
        for side in (elem.left, elem.right):
            col = getattr(side, "_proxies", [side])[0] if hasattr(side, "_proxies") else side
            if (
                getattr(col, "name", None) == "tenant_id"
                and getattr(col, "table", None) is not None
                and _is_tenant_scoped(col.table)
            ):
                return True
    for child in getattr(elem, "get_children", lambda: ())():
        if _walk_for_tenant(child):
            return True
    return False


@event.listens_for(Engine, "before_execute")
def _reject_unscoped_dml(conn, clauseelement, multiparams, params, opts) -> None:
    if opts.get("novamoc_skip_tenant_filter"):
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
                f"{type(clauseelement).__name__} against {[t.name for t in scoped]} "
                f"has no tenant_id predicate"
            )
```

- [ ] **Step 4: Run Layer 3 tests to verify they pass**

Run: `uv run pytest tests/db/test_layer3_before_execute.py -v`
Expected: 5 PASS.

If `_values_carries_tenant` or `_whereclause_filters_tenant` shape doesn't match what SQLAlchemy 2.x actually exposes, the tests show which case fails — adjust the helper to match. The helpers are intentionally conservative; false negatives are fix-the-helper bugs, not data-leak bugs.

- [ ] **Step 5: Run all listener tests**

Run: `uv run pytest tests/db/ -v`
Expected: All Layer 1, 2, 3, plus contextvar and EventLog-monotonicity tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/_listeners.py tests/db/test_layer3_before_execute.py
git commit -m "feat(db): Layer 3 — before_execute rejects unscoped DML (issue #51)"
```

---

## Task 10: Wire listener import into `asgi.py` and `conftest.py`

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `tests/conftest.py`
- Test: `tests/db/test_listener_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_listener_wiring.py
"""The listeners must be active for the conftest's session/engine fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db._errors import UnscopedQueryError
from novamoc.db.models.schema._asset_type import AssetType


@pytest.mark.asyncio
async def test_session_fixture_has_listeners_active(session: AsyncSession) -> None:
    """Without the contextvar, even the session fixture rejects flushes."""
    session.add(AssetType(name="Truck", active=True))
    with pytest.raises(UnscopedQueryError):
        await session.flush()
```

- [ ] **Step 2: Run to verify it fails (or passes coincidentally)**

Run: `uv run pytest tests/db/test_listener_wiring.py -v`
Expected: depends on whether prior tests imported `novamoc.db._listeners`; if yes, this test passes; if no, the AssetType insert silently succeeds because the `before_flush` hook isn't registered.

The intent is to prove that `conftest.py` wires the listeners explicitly. Continue.

- [ ] **Step 3: Add listener import to `tests/conftest.py`**

Add after `import novamoc.db.models  # noqa: F401`:

```python
import novamoc.db._listeners  # noqa: F401  -- registers tenant-scoping listeners
```

- [ ] **Step 4: Add listener import to `src/py/novamoc/asgi.py`**

Inside `create_app()`, near the top imports (or at module level if no circular import):

```python
import novamoc.db._listeners  # noqa: F401  -- registers tenant-scoping listeners
```

- [ ] **Step 5: Run the wiring test**

Run: `uv run pytest tests/db/test_listener_wiring.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py src/py/novamoc/asgi.py tests/db/test_listener_wiring.py
git commit -m "feat: register tenant-scoping listeners on app + test boot"
```

---

## Task 11: `TenantContextMiddleware` + asgi wiring

**Files:**
- Modify: `src/py/novamoc/domain/accounts/_middleware.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Modify: `src/py/novamoc/asgi.py`
- Test: `tests/accounts/test_tenant_context_middleware.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/accounts/test_tenant_context_middleware.py
from __future__ import annotations

from typing import Any

import pytest
from litestar.testing import AsyncTestClient

from novamoc.db._tenant_context import current_tenant_id


@pytest.mark.asyncio
async def test_middleware_sets_contextvar_during_request(client: AsyncTestClient[Any]) -> None:
    seen: list[str | None] = []

    @client.app.get("/__tenant_probe")
    async def probe() -> dict[str, str | None]:
        seen.append(current_tenant_id.get())
        return {"ok": "yes"}

    # The conftest client fixture attaches the dev bearer token by default;
    # see tests/accounts for the exact fixture wiring.
    response = await client.get(
        "/__tenant_probe", headers={"Authorization": "Bearer t1-dev-token"}
    )
    assert response.status_code == 200
    assert seen == ["t1"]


@pytest.mark.asyncio
async def test_middleware_resets_contextvar_after_request(client: AsyncTestClient[Any]) -> None:
    await client.get(
        "/openapi/openapi.json",  # bypassed by AuthenticationMiddleware
    )
    # After the request, the test process's contextvar should still be the
    # default (None). The reset is in finally, so even error paths reset.
    assert current_tenant_id.get() is None
```

(If registering ad-hoc routes on the app fixture isn't supported, replace the `probe` route with a temporary handler in conftest, or assert via a small wrapper that records the contextvar value during a real schema endpoint call.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/accounts/test_tenant_context_middleware.py -v`
Expected: FAIL — `TenantContextMiddleware` doesn't exist; or the contextvar is `None` during the request.

- [ ] **Step 3: Implement `TenantContextMiddleware`**

Append to `src/py/novamoc/domain/accounts/_middleware.py` (alongside `AuthenticationMiddleware`):

```python
from litestar.middleware import ASGIMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send

from novamoc.db._tenant_context import current_tenant_id


class TenantContextMiddleware(ASGIMiddleware):
    """Bind the per-request RequestAuth.tenant_id to the storage-layer
    ContextVar.

    Stacks after AuthenticationMiddleware so scope["auth"] is already
    populated. Resets the contextvar on the way out, including
    exception paths.
    """

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

- [ ] **Step 4: Re-export from `domain/accounts/__init__.py`**

```python
from novamoc.domain.accounts._middleware import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
)
```

(Keep the existing `__all__` and add `"TenantContextMiddleware"`.)

- [ ] **Step 5: Add to asgi middleware list**

In `src/py/novamoc/asgi.py`, change:

```python
middleware=[
    DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
],
```

to:

```python
middleware=[
    DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
    DefineMiddleware(TenantContextMiddleware),
],
```

Add `TenantContextMiddleware` to the import from `novamoc.domain.accounts`.

- [ ] **Step 6: Run the middleware test**

Run: `uv run pytest tests/accounts/test_tenant_context_middleware.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/accounts/_middleware.py src/py/novamoc/domain/accounts/__init__.py src/py/novamoc/asgi.py tests/accounts/test_tenant_context_middleware.py
git commit -m "feat(accounts): TenantContextMiddleware sets current_tenant_id"
```

---

## Task 12: Update test fixtures so the existing suite is green

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/data/loader.py`
- Modify: `tests/data/fixtures/truck/asset_type.json`
- Modify: `tests/data/fixtures/truck/asset_type__deactivated.json`
- Modify: `tests/data/fixtures/truck/asset_type_field__vin.json`

The post-listener world needs the contextvar set during seed and direct service tests. Strip `tenant_id` from JSON fixtures (Layer 2 stamps it) and have the seed fixture run under `use_tenant("t1")` by default.

- [ ] **Step 1: Strip `tenant_id` from each fixture file**

```bash
# Read each file, remove the "tenant_id": "t1" line.
```

For example, `tests/data/fixtures/truck/asset_type.json` becomes:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000001",
    "name": "Truck",
    "active": true
  }
]
```

Apply the same edit to `asset_type__deactivated.json` and `asset_type_field__vin.json`.

- [ ] **Step 2: Update `tests/data/loader.py` to accept a tenant_id override**

Read the file with the Read tool first. Add a `tenant_id` keyword parameter to `load_scenario`:

```python
async def load_scenario(
    scenario: Scenario,
    *,
    session: AsyncSession,
    services: ServiceBundle,
    tenant_id: str = "t1",
) -> Mapping[str, Mapping[str, UUID]]:
    """Load the scenario under ``tenant_id`` (default 't1').

    Wraps the loads in ``use_tenant(tenant_id)`` so Layer 2's
    auto-stamp populates each row's tenant_id from the contextvar.
    """
    from novamoc.db._tenant_context import use_tenant
    exports: dict[str, dict[str, UUID]] = {}
    with use_tenant(tenant_id):
        for path in scenario:
            entity_dir, basename = path.split("/", 1)
            service_attr = _service_attr_for(basename)
            rows = await open_fixture_async(FIXTURES_PATH / entity_dir, basename)
            await getattr(services, service_attr).create_many(
                data=rows,
                auto_commit=False,
            )
            bucket = exports.setdefault(service_attr, {})
            for row in rows:
                bucket[row["name"]] = UUID(row["id"])
        await session.flush()
    return exports
```

- [ ] **Step 3: Update the `seed` fixture to pass through `tenant_id`**

In `tests/conftest.py`, change:

```python
async def _seed(scenario: Scenario) -> Mapping[str, Mapping[str, UUID]]:
    return await load_scenario(scenario, session=session, services=services)
```

to:

```python
async def _seed(
    scenario: Scenario, *, tenant_id: str = "t1"
) -> Mapping[str, Mapping[str, UUID]]:
    return await load_scenario(
        scenario, session=session, services=services, tenant_id=tenant_id
    )
```

- [ ] **Step 4: Run the full suite**

Run: `just test-py`
Expected: All previously-passing tests pass again; the listener tests still pass; cross-tenant isolation tests don't exist yet.

If a handler test fails because the test body calls a service method (e.g., `services.asset_type.get_one_or_none(...)`) without `use_tenant(...)` and without depending on `seed`, wrap that test's body in `use_tenant("t1")`. Such tests are exercising direct service surface; the contextvar is required by the new architecture.

- [ ] **Step 5: Commit**

```bash
git add -A tests/
git commit -m "test: contextvar-aware fixtures + tenant-agnostic JSON fixtures"
```

---

## Task 13: Drop `tenant_id` from handler reads and creates

**Files:**
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type_field.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`

Mechanical refactor — covered by the existing schema-endpoint test suite.

- [ ] **Step 1: Edit `asset_type.py`**

For each handler in the file:

- In `get_one_or_none(...)` calls: drop `tenant_id=auth.tenant_id`.
- In `create(data={...})` calls: drop `"tenant_id": auth.tenant_id` from the data dict.
- Leave `update(item_id=(auth.tenant_id, req.entity_id), ...)` and `delete(item_id=(auth.tenant_id, req.entity_id), ...)` unchanged — the composite item_id is required to identify the row.
- Leave `change_log.append(tenant_id=auth.tenant_id, ...)` unchanged for now — Task 14 simplifies that signature.

Example diff for the `activate` handler:

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
    data={
        "tenant_id": auth.tenant_id,
        "id": req.entity_id,
        "name": req.payload.name,
        "active": True,
    },
    auto_commit=False,
)

# After:
await services.asset_type.create(
    data={
        "id": req.entity_id,
        "name": req.payload.name,
        "active": True,
    },
    auto_commit=False,
)
```

- [ ] **Step 2: Apply the same edits to the other three handler files**

`asset_type_field.py`, `maintenance_record_type.py`, `maintenance_record_type_field.py` — same patterns.

- [ ] **Step 3: Run the schema endpoint suite**

Run: `uv run pytest tests/schema/ -v`
Expected: PASS — the listener layers fill in the dropped scoping.

- [ ] **Step 4: Commit**

```bash
git add src/py/novamoc/domain/schema/_handlers/
git commit -m "refactor(schema): drop redundant tenant_id from handler reads/creates"
```

---

## Task 14: Simplify services — collapse `list_for_tenant`, drop tenant from change-log

**Files:**
- Modify: `src/py/novamoc/domain/schema/services/_asset_type.py`
- Modify: `src/py/novamoc/domain/schema/services/_asset_type_field.py`
- Modify: `src/py/novamoc/domain/schema/services/_maintenance_record_type.py`
- Modify: `src/py/novamoc/domain/schema/services/_maintenance_record_type_field.py`
- Modify: `src/py/novamoc/domain/schema/services/_change_log.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type.py`, `_handlers/asset_type_field.py`, `_handlers/maintenance_record_type.py`, `_handlers/maintenance_record_type_field.py`

- [ ] **Step 1: Remove `list_for_tenant` from each projection service**

For each of the four projection services:

```python
# Delete the list_for_tenant method entirely. The class becomes:
class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetType]):
        model_type = m.schema.AssetType

    repository_type = Repo
```

- [ ] **Step 2: Move `OrderBy` into the controller**

In `src/py/novamoc/domain/schema/controllers/_schema.py`, the GET handler currently calls (e.g.) `services.asset_type.list_for_tenant(...)`. Change to `services.asset_type.list(OrderBy(field_name="id"))`. Repeat for the field service with `OrderBy(field_name="parent_id"), OrderBy(field_name="id")`.

(Read the controller file with the Read tool first to see the exact call shape — the test_endpoint_e2e tests assert byte-equal ETags so ordering must remain identical.)

- [ ] **Step 3: Simplify `SchemaChangeLogService`**

```python
# src/py/novamoc/domain/schema/services/_change_log.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.extensions.litestar import repository, service
from sqlalchemy import func, select

import novamoc.db.models as m
from novamoc.domain.schema._commands import SchemaCommand


class SchemaChangeLogService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.SchemaChangeLog]
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.SchemaChangeLog]):
        model_type = m.schema.SchemaChangeLog

    repository_type = Repo

    async def append(
        self,
        *,
        command: SchemaCommand,
        entity_id: UUID,
        payload: dict[str, Any],
    ) -> m.schema.SchemaChangeLog:
        next_seq = await self.current_version() + 1
        return await self.create(
            data={
                "seq": next_seq,
                "command": str(command.value),
                "entity_id": entity_id,
                "payload": payload,
            },
            auto_commit=False,
        )

    async def current_version(self) -> int:
        """Return the tenant's current schema_version (MAX(seq) or 0).

        Tenant filter is supplied by Layer 1; the SELECT is ORM-flavoured
        so loader_criteria attaches to it.
        """
        stmt = select(func.coalesce(func.max(m.schema.SchemaChangeLog.seq), 0))
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())
```

> Implementation note for `current_version`: if Layer 1 doesn't attach loader-criteria to a `select(func.coalesce(...))` (the SELECT has no entity FROM), this method will return cross-tenant max. Test exists in Task 16 to catch this; if it fails, rewrite as `select(SchemaChangeLog.seq).order_by(SchemaChangeLog.seq.desc()).limit(1)` which is an entity-load form that loader-criteria definitely sees.

- [ ] **Step 4: Update handler call sites that pass `tenant_id` to change_log**

In each of the four handlers, change:

```python
row = await services.change_log.append(
    tenant_id=auth.tenant_id,
    command=...,
    entity_id=req.entity_id,
    payload=...,
)
```

to:

```python
row = await services.change_log.append(
    command=...,
    entity_id=req.entity_id,
    payload=...,
)
```

- [ ] **Step 5: Update the GET /schema controller's `current_version` call**

Change `services.change_log.current_version(tenant_id=...)` to `services.change_log.current_version()`.

- [ ] **Step 6: Run schema endpoint tests**

Run: `uv run pytest tests/schema/ -v`
Expected: PASS. ETag-byte-equality tests still pass because the `OrderBy` moved to the controller (same calls, same order).

If `test_get_schema_returns_correct_version_for_empty_tenant` fails because `current_version()` returned a cross-tenant max, swap the implementation to the entity-load form (see implementation note in Step 3).

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/schema/services/ src/py/novamoc/domain/schema/controllers/_schema.py src/py/novamoc/domain/schema/_handlers/
git commit -m "refactor(schema): drop list_for_tenant; simplify change_log service"
```

---

## Task 15: Add `TWO_TENANT_TRUCK` scenario

**Files:**
- Modify: `tests/data/scenarios.py`

The cross-tenant test loads the same fixture under two tenants. With Layer 2 auto-stamp and the loader's `tenant_id` override, no new fixture file is needed — the scenarios layer just needs a name to refer to.

- [ ] **Step 1: Add the scenario tuple**

Append to `tests/data/scenarios.py`:

```python
TWO_TENANT_TRUCK: Scenario = ("truck/asset_type",)
"""Same-shape AssetType under multiple tenants.

The cross-tenant isolation test loads this scenario twice — once
under tenant_id='t-a' and once under tenant_id='t-b' — to seed
equivalent rows under both tenants. Per-tenant tenant_id stamping
is supplied by Layer 2; the JSON fixture is tenant-agnostic.
"""
```

- [ ] **Step 2: Commit**

```bash
git add tests/data/scenarios.py
git commit -m "test: add TWO_TENANT_TRUCK scenario for cross-tenant tests"
```

---

## Task 16: Cross-tenant isolation test — the issue's headline

**Files:**
- Test: `tests/schema/test_cross_tenant_isolation.py`

This is the test that pins the issue's acceptance criteria.

- [ ] **Step 1: Write the test file**

```python
# tests/schema/test_cross_tenant_isolation.py
"""Cross-tenant isolation — every service method scopes correctly.

Issue #51 acceptance criterion: seeding equivalent rows under two
tenants and exercising every read/write method must show no leak.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from advanced_alchemy.filters import OrderBy

from novamoc.db._errors import UnscopedQueryError
from novamoc.db._tenant_context import use_tenant
from novamoc.domain.schema._bundle import ServiceBundle
from tests.data.scenarios import TWO_TENANT_TRUCK


@pytest.fixture
async def two_tenant_ids(seed) -> dict[str, UUID]:
    """Seed TWO_TENANT_TRUCK under t-a and t-b, return their ids."""
    a = await seed(TWO_TENANT_TRUCK, tenant_id="t-a")
    b = await seed(TWO_TENANT_TRUCK, tenant_id="t-b")
    return {
        "t-a": a["asset_type"]["Truck"],
        "t-b": b["asset_type"]["Truck"],
    }


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
@pytest.mark.asyncio
async def test_list_returns_only_own_rows(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    with use_tenant(tenant):
        rows = await services.asset_type.list(OrderBy(field_name="id"))
    assert {r.tenant_id for r in rows} == {tenant}
    assert len(rows) == 1


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
@pytest.mark.asyncio
async def test_get_one_or_none_does_not_leak_other_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    other = "t-b" if tenant == "t-a" else "t-a"
    with use_tenant(tenant):
        own = await services.asset_type.get_one_or_none(id=two_tenant_ids[tenant])
        cross = await services.asset_type.get_one_or_none(id=two_tenant_ids[other])
    assert own is not None
    assert own.tenant_id == tenant
    assert cross is None


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
@pytest.mark.asyncio
async def test_count_and_exists_are_per_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    with use_tenant(tenant):
        assert await services.asset_type.count() == 1
        assert await services.asset_type.exists(name="Truck") is True


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
@pytest.mark.asyncio
async def test_update_does_not_touch_other_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    own_id = two_tenant_ids[tenant]
    other = "t-b" if tenant == "t-a" else "t-a"
    other_id = two_tenant_ids[other]
    with use_tenant(tenant):
        await services.asset_type.update(
            data={"name": "Lorry"},
            item_id=(tenant, own_id),
            auto_commit=False,
        )
    # Verify by reading under each tenant.
    with use_tenant(tenant):
        my_row = await services.asset_type.get_one_or_none(id=own_id)
    with use_tenant(other):
        other_row = await services.asset_type.get_one_or_none(id=other_id)
    assert my_row is not None and my_row.name == "Lorry"
    assert other_row is not None and other_row.name == "Truck"


@pytest.mark.asyncio
async def test_select_without_tenant_context_raises(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID]
) -> None:
    # No use_tenant here.
    with pytest.raises(UnscopedQueryError):
        await services.asset_type.list()


@pytest.mark.asyncio
async def test_create_without_context_raises(services: ServiceBundle) -> None:
    with pytest.raises(UnscopedQueryError):
        await services.asset_type.create(
            data={
                "id": UUID("11111111-1111-1111-1111-111111111111"),
                "name": "Z",
                "active": True,
            },
            auto_commit=False,
        )


@pytest.mark.asyncio
async def test_create_with_mismatched_tenant_id_raises(services: ServiceBundle) -> None:
    from novamoc.db._errors import CrossTenantWriteError

    with use_tenant("t-a"):
        with pytest.raises(CrossTenantWriteError):
            await services.asset_type.create(
                data={
                    "tenant_id": "t-b",
                    "id": UUID("22222222-2222-2222-2222-222222222222"),
                    "name": "Z",
                    "active": True,
                },
                auto_commit=False,
            )
```

- [ ] **Step 2: Run the test file**

Run: `uv run pytest tests/schema/test_cross_tenant_isolation.py -v`
Expected: PASS — every parametrised case under both tenants, plus the negative cases.

If a method like `services.asset_type.exists(name="Truck")` fails because advanced-alchemy doesn't support keyword filters on `exists`, replace with `await services.asset_type.exists(AssetType.name == "Truck")` or skip that assertion. Goal is to prove every method scopes — exact API shape is secondary.

- [ ] **Step 3: Run the full suite**

Run: `just test-py`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/schema/test_cross_tenant_isolation.py
git commit -m "test(schema): cross-tenant isolation across every service method (#51)"
```

---

## Task 17: Final verification + lint/format/typecheck

**Files:**
- (none modified — verification only)

- [ ] **Step 1: Run all checks**

Run: `just check`
Expected: PASS (lint, format, typecheck).

- [ ] **Step 2: Run the full test suite**

Run: `just test`
Expected: PASS.

- [ ] **Step 3: Spot-check the headline test once more**

Run: `uv run pytest tests/schema/test_cross_tenant_isolation.py tests/db/ -v`
Expected: PASS.

- [ ] **Step 4: Confirm no leftover `tenant_id=auth.tenant_id` in handlers**

Run via Grep tool on `pattern="tenant_id=auth\\.tenant_id"`, paths under `src/py/novamoc/domain/schema/_handlers/`.
Expected: no matches (handlers no longer pass it for reads/creates; updates/deletes use `item_id=(auth.tenant_id, ...)` which is a different shape).

- [ ] **Step 5: Confirm no leftover `list_for_tenant`**

Run via Grep: `pattern="list_for_tenant"`.
Expected: no matches anywhere.

- [ ] **Step 6: Final commit (if any cleanup landed)**

Otherwise no commit. Branch is ready for review.

---

## Self-review notes

Spec coverage:

- Layer 1 (do_orm_execute) — Task 8.
- Layer 2 (before_flush) — Task 7.
- Layer 3 (before_execute) — Task 9.
- ContextVar + `use_tenant` + `SKIP_TENANT_FILTER` — Task 2.
- `TenantScopedMixin` + `_mixins.py` — Task 3.
- Removal of `TenantScopedAuditBase` + projection-table refactor — Task 4.
- `SchemaChangeLog` mixin adoption — Task 5.
- `EventLog` composite-PK refactor + monotonicity verification — Task 6.
- Listener wiring imports — Task 10.
- `TenantContextMiddleware` + asgi stack — Task 11.
- Fixture / conftest / loader updates — Task 12.
- Handler simplification — Task 13.
- Service simplification (collapse `list_for_tenant`, change_log signatures, controller `OrderBy`) — Task 14.
- `TWO_TENANT_TRUCK` scenario — Task 15.
- Cross-tenant isolation test (headline acceptance criterion) — Task 16.
- Final verification — Task 17.

Each spec section has a corresponding task. No gaps.
