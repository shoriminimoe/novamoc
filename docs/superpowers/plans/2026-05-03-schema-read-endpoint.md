# Schema Read Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GET /schema/{tenant_id}` per the design at `docs/superpowers/specs/2026-05-03-schema-read-endpoint-design.md` — a single-snapshot read of the per-tenant schema projection, with `schema_version`-as-ETag conditional GET, 404 for unknown tenants gated by a hardcoded `KNOWN_TENANT_IDS`, and tombstones included so clients can validate events targeting `deactivate_*`-d fields.

**Architecture:** New read-side handler on the existing `SchemaController` (which already owns `/schema`). Reuses the four projection services and adds one method to `SchemaChangeLogService` for the `MAX(seq)` lookup. Response shape lives in a sibling `_read_payloads.py` so command/response payloads stay separable. Errors flow through the existing `ProblemDetailsPlugin`; the `SchemaCommandError` base is renamed to `SchemaError` so a new read-side `TenantNotFoundError` can share the rendering pipeline.

**Tech Stack:** Python 3.14, Litestar, msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, pytest (asyncio auto mode), uv, ruff, ty.

---

## File map

**Created:**
- `src/py/novamoc/domain/schema/_read_payloads.py` — `msgspec.Struct` response shapes for the read endpoint (`SchemaSnapshotResponse`, `AssetTypeView`, `AssetTypeFieldView`, maintenance-record analogues).
- `tests/schema/test_read_payloads.py` — encode round-trip tests for the response structs.
- `tests/schema/test_change_log_service_current_version.py` — unit test for the new `current_version` service method.
- `tests/schema/test_read_endpoint_e2e.py` — E2E HTTP tests for the new endpoint (200 empty / 200 populated / tombstones / 404 / ETag / 304).

**Modified:**
- `src/py/novamoc/config.py` — currently empty; add `KNOWN_TENANT_IDS: frozenset[str]`.
- `src/py/novamoc/domain/schema/_errors.py` — rename `SchemaCommandError` → `SchemaError`; add `ErrorCode.TENANT_NOT_FOUND`, `_DEFAULT_MESSAGES` entry, `TenantNotFoundError(SchemaError)`.
- `src/py/novamoc/api/_problem_details.py` — rename mapper `schema_command_error_to_problem_details` → `schema_error_to_problem_details`; add `_TITLES` and `_STATUS_CODES` entries for `TENANT_NOT_FOUND`; update import + docstring.
- `src/py/novamoc/asgi.py` — update import + map registration to renamed symbols.
- `src/py/novamoc/domain/schema/services/_change_log.py` — add `current_version(tenant_id)` returning `int`.
- `src/py/novamoc/domain/schema/controllers/_schema.py` — add a `@get("/{tenant_id:str}")` handler; update docstring reference from `SchemaCommandError` to `SchemaError`.
- `tests/conftest.py` — update import + `exception_to_problem_detail_map` registration to the renamed symbols.
- `tests/api/test_problem_details.py` — update import + call sites to the renamed mapper.

---

## Conventions

- **TDD throughout.** Every behavioural task starts with a failing test. Watch the test fail before implementing.
- **No DB mocks.** All DB-touching tests use the real in-memory aiosqlite (per `tests/conftest.py`).
- **`uv run` everything.** Tests, lint, type-check all go through `uv run` so the project's pinned deps and Python 3.14 toolchain are used.
- **`pytest` is in asyncio auto mode** — async tests do not need `@pytest.mark.asyncio`.
- **Frequent commits.** One commit per task; the working tree is left clean and tests passing at every commit boundary. Hooks are honoured (no `--no-verify`).
- **Tenant in fixtures.** The existing test fixture set uses `tenant_id: "t1"` (`tests/data/fixtures/truck/asset_type.json`). The plan picks `"t1"` as the dev tenant so the new tests can reuse the existing seeding machinery without duplicating fixtures. This is the dev shortcut tracked by [#19](https://github.com/shoriminimoe/novamoc/issues/19) — production tenant identity is out of scope.

---

## Task 1: Add `KNOWN_TENANT_IDS` to `config.py`

**Files:**
- Modify: `src/py/novamoc/config.py`

This task is small and isolated. No dedicated test — the constant is consumed by the controller in Task 6 and is implicitly tested there.

- [ ] **Step 1: Confirm the file is empty and create the constant**

Read first to confirm:

```bash
cat src/py/novamoc/config.py
```

Expected: empty file (0 bytes).

Replace its contents with:

```python
"""Application-level configuration constants.

Today this is a thin module — most config is wired in :mod:`novamoc.asgi`
via the SQLAlchemy plugin. Constants here are values that need to be
referenced from multiple places and would otherwise live as string
literals scattered across the code.
"""

from __future__ import annotations

# Single hardcoded tenant for the pre-auth dev environment. Aligned with
# the existing test fixtures under ``tests/data/fixtures/`` which seed
# ``tenant_id: "t1"``. Replaced by a real tenant registry once auth and
# tenant management land — see issue #19.
KNOWN_TENANT_IDS: frozenset[str] = frozenset({"t1"})
```

- [ ] **Step 2: Lint and type-check the change**

```bash
uv run ruff check src/py/novamoc/config.py
uv run ruff format --check src/py/novamoc/config.py
uv run ty check
```

Expected: all clean.

- [ ] **Step 3: Run the existing test suite to confirm nothing regressed**

```bash
uv run pytest
```

Expected: 107 passed (same as the baseline).

- [ ] **Step 4: Commit**

```bash
git add src/py/novamoc/config.py
git commit -m "feat(config): add KNOWN_TENANT_IDS dev tenant registry stub"
```

---

## Task 2: Rename `SchemaCommandError` → `SchemaError` and add `tenant_not_found` error

**Files:**
- Modify: `src/py/novamoc/domain/schema/_errors.py`
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `src/py/novamoc/asgi.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py` (docstring only)
- Modify: `tests/conftest.py`
- Modify: `tests/api/test_problem_details.py`

This is one cohesive commit because the rename and the new code are interlocked across files; intermediate states would not import or pass tests.

- [ ] **Step 1: Update `_errors.py` — rename base, add code + subclass**

Replace the contents of `src/py/novamoc/domain/schema/_errors.py` with:

```python
"""Typed exceptions raised by schema endpoints (commands and reads).

Each exception carries an ``ErrorCode`` (the stable failure-mode
identifier), an optional human-readable message, and a free-form
mapping of extras for per-failure context (e.g., the conflicting
name on a name-collision). Subclasses categorize failures; handlers
raise the most specific one that fits.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    PAYLOAD_NO_CHANGES = "payload_no_changes"
    INVALID_PAYLOAD_SHAPE = "invalid_payload_shape"
    NAME_RESERVED = "name_reserved"
    PARENT_TYPE_NOT_FOUND = "parent_type_not_found"
    ENTITY_NOT_FOUND = "entity_not_found"
    TENANT_NOT_FOUND = "tenant_not_found"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Request payload did not match the expected shape.",
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
    ErrorCode.TENANT_NOT_FOUND: "Tenant not found.",
}


class SchemaError(Exception):
    """Base class for schema endpoint failures (command and read alike)."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str | None = None,
        **extras: Any,
    ) -> None:
        super().__init__(message or _DEFAULT_MESSAGES[code])
        self.code = code
        self.message = message or _DEFAULT_MESSAGES[code]
        self.extras = extras


class PayloadShapeError(SchemaError):
    """Request payload was well-formed but did not match the command's
    expectations (missing required fields, empty update, ...)."""


class ConflictError(SchemaError):
    """Request conflicted with the current projection state (name
    already taken, parent type missing, ...)."""


class EntityNotFoundError(SchemaError):
    """Command targeted an entity that does not exist."""


class TenantNotFoundError(SchemaError):
    """Request targeted a tenant that the server does not know about."""
```

- [ ] **Step 2: Update `_problem_details.py` — rename mapper, add new code entries**

Edit `src/py/novamoc/api/_problem_details.py` in place. Apply these changes:

Replace the docstring opening:

```python
"""RFC 9457 problem-details rendering for the whole API.

The `ProblemDetails` msgspec struct is published as the OpenAPI response
body for every error path. The converters below turn typed exceptions
(`SchemaError`, msgspec/Litestar validation errors, eventually
others) into Litestar's `ProblemDetailsException`, which the
`ProblemDetailsPlugin` renders as `application/problem+json`.
```

(Only the `SchemaCommandError` reference inside the docstring changes to `SchemaError`.)

Replace the import:

```python
from novamoc.domain.schema._errors import (
    ErrorCode,
    SchemaError,
)
```

Add entries to `_TITLES` and `_STATUS_CODES`:

```python
_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
    ErrorCode.TENANT_NOT_FOUND: "Tenant not found",
}


_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.PAYLOAD_NO_CHANGES: 400,
    ErrorCode.INVALID_PAYLOAD_SHAPE: 400,
    ErrorCode.NAME_RESERVED: 409,
    ErrorCode.PARENT_TYPE_NOT_FOUND: 409,
    ErrorCode.ENTITY_NOT_FOUND: 404,
    ErrorCode.TENANT_NOT_FOUND: 404,
}
```

Rename the mapper function:

```python
def schema_error_to_problem_details(
    exc: SchemaError,
) -> ProblemDetailsException:
    """Convert a `SchemaError` to a `ProblemDetailsException`.

    The plugin's response renderer flattens `extra` into top-level keys
    when it is a Mapping (RFC 9457 §3.2 extension members).
    """

    return ProblemDetailsException(
        type_=_type_uri(exc.code),
        title=_TITLES[exc.code],
        status_code=_STATUS_CODES[exc.code],
        detail=exc.message,
        instance=make_instance(),
        extra=dict(exc.extras) if exc.extras else None,
    )
```

- [ ] **Step 3: Update `asgi.py`**

In `src/py/novamoc/asgi.py` change the imports and the map entry:

```python
from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
)
from novamoc.domain.schema._errors import SchemaError
```

```python
problem_details_config = ProblemDetailsConfig(
    enable_for_all_http_exceptions=True,
    exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
        SchemaError: schema_error_to_problem_details,
        msgspec.ValidationError: msgspec_validation_error_to_problem_details,
        ValidationException: litestar_validation_error_to_problem_details,
    },
)
```

- [ ] **Step 4: Update `tests/conftest.py`**

Apply the same import and map update as in `asgi.py`:

```python
from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
)
from novamoc.domain.schema._errors import SchemaError
```

```python
exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
    SchemaError: schema_error_to_problem_details,
    msgspec.ValidationError: msgspec_validation_error_to_problem_details,
    ValidationException: litestar_validation_error_to_problem_details,
},
```

- [ ] **Step 5: Update `tests/api/test_problem_details.py`**

Update the import and the three call sites that reference the old mapper name:

```python
from novamoc.api._problem_details import (
    ProblemDetails,
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
)
```

In `test_schema_command_error_conflict_renders_409_with_extras`,
`test_schema_command_error_payload_shape_renders_400`, and
`test_schema_command_error_entity_not_found_renders_404`, replace
`schema_command_error_to_problem_details(exc)` with
`schema_error_to_problem_details(exc)`. Function names of the test cases
themselves are left as-is (they're describing the behaviour, not the
mapper symbol).

- [ ] **Step 6: Update the controller docstring**

In `src/py/novamoc/domain/schema/controllers/_schema.py`, change the line:

```
``novamoc.asgi.create_app``: ``SchemaCommandError``,
```

to:

```
``novamoc.asgi.create_app``: ``SchemaError``,
```

- [ ] **Step 7: Run lint, type-check, and tests**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
uv run pytest
```

Expected: 107 passed, no lint or type errors. The rename is mechanical; no behaviour has changed.

- [ ] **Step 8: Commit**

```bash
git add src/py/novamoc/domain/schema/_errors.py \
        src/py/novamoc/api/_problem_details.py \
        src/py/novamoc/asgi.py \
        src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/conftest.py \
        tests/api/test_problem_details.py
git commit -m "refactor(errors): rename SchemaCommandError to SchemaError and add tenant_not_found"
```

---

## Task 3: Add a unit test for the renamed mapper covering `tenant_not_found`

**Files:**
- Modify: `tests/api/test_problem_details.py`

The existing tests cover the other four error codes; add one for the new `TENANT_NOT_FOUND` so the rendering path is exercised before the controller starts depending on it.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_problem_details.py`:

```python
def test_schema_error_tenant_not_found_renders_404_with_extras() -> None:
    from novamoc.domain.schema._errors import TenantNotFoundError

    exc = TenantNotFoundError(code=ErrorCode.TENANT_NOT_FOUND, tenant_id="who-dis")
    pd_exc = schema_error_to_problem_details(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "urn:novamoc:problems:tenant_not_found"
    assert pd_exc.title == "Tenant not found"
    assert pd_exc.extra == {"tenant_id": "who-dis"}
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
uv run pytest tests/api/test_problem_details.py::test_schema_error_tenant_not_found_renders_404_with_extras -v
```

Expected: PASS — the rendering wiring was put in place by Task 2; this test confirms it.

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest
```

Expected: 108 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_problem_details.py
git commit -m "test(api): cover tenant_not_found problem-details rendering"
```

---

## Task 4: Add `SchemaChangeLogService.current_version`

**Files:**
- Create: `tests/schema/test_change_log_service_current_version.py`
- Modify: `src/py/novamoc/domain/schema/services/_change_log.py`

The endpoint needs the per-tenant `MAX(seq)`, defaulting to `0` for an empty tenant. Add it as a service method so the controller stays at the orchestration layer.

- [ ] **Step 1: Write the failing test**

Create `tests/schema/test_change_log_service_current_version.py` with:

```python
from __future__ import annotations

from uuid import uuid4

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService


async def test_current_version_returns_zero_for_empty_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    assert await svc.current_version(tenant_id="t1") == 0


async def test_current_version_returns_max_seq_for_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    for _ in range(3):
        await svc.append(
            tenant_id="t1",
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={},
        )
    await session.flush()

    version = await svc.current_version(tenant_id="t1")
    assert version >= 3  # globally monotonic, so exact value depends on prior tests


async def test_current_version_is_per_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    await svc.append(
        tenant_id="t-other",
        command=SchemaCommand.CREATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={},
    )
    await session.flush()

    assert await svc.current_version(tenant_id="t1") == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/schema/test_change_log_service_current_version.py -v
```

Expected: FAIL with `AttributeError: 'SchemaChangeLogService' object has no attribute 'current_version'` (or similar).

- [ ] **Step 3: Implement the method**

Edit `src/py/novamoc/domain/schema/services/_change_log.py`. Add the SQLAlchemy import and the new method:

```python
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
    """Append-only log of accepted schema commands.

    The repository pattern fits poorly here — the table is write-only from
    the endpoint's perspective and each row is one user action — but using
    advanced-alchemy's service keeps Litestar DI uniform across services.
    """

    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.SchemaChangeLog]):
        model_type = m.schema.SchemaChangeLog

    repository_type = Repo

    async def append(
        self,
        *,
        tenant_id: str,
        command: SchemaCommand,
        entity_id: UUID,
        payload: dict[str, Any],
    ) -> m.schema.SchemaChangeLog:
        return await self.create(
            data={
                "tenant_id": tenant_id,
                "command": str(command.value),
                "entity_id": entity_id,
                "payload": payload,
            },
            auto_commit=False,
        )

    async def current_version(self, *, tenant_id: str) -> int:
        """Return ``MAX(seq)`` for the tenant, or ``0`` if none."""
        stmt = select(
            func.coalesce(func.max(m.schema.SchemaChangeLog.seq), 0)
        ).where(m.schema.SchemaChangeLog.tenant_id == tenant_id)
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/schema/test_change_log_service_current_version.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green; total test count up by 3.

- [ ] **Step 6: Commit**

```bash
git add tests/schema/test_change_log_service_current_version.py \
        src/py/novamoc/domain/schema/services/_change_log.py
git commit -m "feat(schema): SchemaChangeLogService.current_version returns per-tenant MAX(seq)"
```

---

## Task 5: Add response payload structs (`_read_payloads.py`)

**Files:**
- Create: `src/py/novamoc/domain/schema/_read_payloads.py`
- Create: `tests/schema/test_read_payloads.py`

Pure msgspec structs — no behaviour, just shape. Tested by encode/decode round-trip.

- [ ] **Step 1: Write the failing test**

Create `tests/schema/test_read_payloads.py`:

```python
from __future__ import annotations

from uuid import UUID

import msgspec

from novamoc.db.models.schema import FieldDataType
from novamoc.domain.schema._read_payloads import (
    AssetTypeFieldView,
    AssetTypeView,
    MaintenanceRecordTypeFieldView,
    MaintenanceRecordTypeView,
    SchemaSnapshotResponse,
)


def test_empty_snapshot_round_trip() -> None:
    snapshot = SchemaSnapshotResponse(
        schema_version=0,
        asset_types=(),
        maintenance_record_types=(),
    )
    decoded = msgspec.json.decode(msgspec.json.encode(snapshot))
    assert decoded == {
        "schema_version": 0,
        "asset_types": [],
        "maintenance_record_types": [],
    }


def test_populated_snapshot_round_trip() -> None:
    asset_type_id = UUID("00000000-0000-0000-0000-000000000001")
    asset_field_id = UUID("00000000-0000-0000-0000-0000000000aa")
    record_type_id = UUID("00000000-0000-0000-0000-000000000002")
    record_field_id = UUID("00000000-0000-0000-0000-0000000000bb")

    snapshot = SchemaSnapshotResponse(
        schema_version=47,
        asset_types=(
            AssetTypeView(
                id=asset_type_id,
                name="Truck",
                active=True,
                fields=(
                    AssetTypeFieldView(
                        id=asset_field_id,
                        name="VIN",
                        data_type=FieldDataType.TEXT,
                        validation=None,
                        active=True,
                    ),
                ),
            ),
        ),
        maintenance_record_types=(
            MaintenanceRecordTypeView(
                id=record_type_id,
                name="Oil change",
                active=False,
                fields=(
                    MaintenanceRecordTypeFieldView(
                        id=record_field_id,
                        name="mileage",
                        data_type=FieldDataType.INTEGER,
                        validation={"min": 0},
                        active=True,
                    ),
                ),
            ),
        ),
    )

    decoded = msgspec.json.decode(msgspec.json.encode(snapshot))
    assert decoded == {
        "schema_version": 47,
        "asset_types": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "Truck",
                "active": True,
                "fields": [
                    {
                        "id": "00000000-0000-0000-0000-0000000000aa",
                        "name": "VIN",
                        "data_type": "text",
                        "validation": None,
                        "active": True,
                    }
                ],
            }
        ],
        "maintenance_record_types": [
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "name": "Oil change",
                "active": False,
                "fields": [
                    {
                        "id": "00000000-0000-0000-0000-0000000000bb",
                        "name": "mileage",
                        "data_type": "integer",
                        "validation": {"min": 0},
                        "active": True,
                    }
                ],
            }
        ],
    }
```

If `FieldDataType.INTEGER` doesn't exist in the enum, substitute the actual integer-typed member. To check, run:

```bash
uv run python -c "from novamoc.db.models.schema import FieldDataType; print(list(FieldDataType))"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/schema/test_read_payloads.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novamoc.domain.schema._read_payloads'`.

- [ ] **Step 3: Implement the structs**

Create `src/py/novamoc/domain/schema/_read_payloads.py`:

```python
"""Wire-format response structs for ``GET /schema/{tenant_id}``.

Kept separate from :mod:`novamoc.domain.schema._payloads` (which holds
the command-side discriminated union) so the two concerns don't pile
into one file. View structs are passive shapes — no discriminator, no
defaults — they exist so the controller can hand a typed object to the
serializer instead of a hand-built dict.

Field nesting mirrors the conceptual shape (a type owns its fields).
``active`` is included on every row; clients filter at read time per use
case (see ADR-008 / ADR-009 / the design spec).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import msgspec

from novamoc.db.models.schema import FieldDataType


class AssetTypeFieldView(msgspec.Struct):
    id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None
    active: bool


class AssetTypeView(msgspec.Struct):
    id: UUID
    name: str
    active: bool
    fields: tuple[AssetTypeFieldView, ...]


class MaintenanceRecordTypeFieldView(msgspec.Struct):
    id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None
    active: bool


class MaintenanceRecordTypeView(msgspec.Struct):
    id: UUID
    name: str
    active: bool
    fields: tuple[MaintenanceRecordTypeFieldView, ...]


class SchemaSnapshotResponse(msgspec.Struct):
    schema_version: int
    asset_types: tuple[AssetTypeView, ...]
    maintenance_record_types: tuple[MaintenanceRecordTypeView, ...]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/schema/test_read_payloads.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/_read_payloads.py \
        tests/schema/test_read_payloads.py
git commit -m "feat(schema): response payload structs for GET /schema/{tenant_id}"
```

---

## Task 6: Add `GET /schema/{tenant_id}` — happy path (200 with empty + populated body)

**Files:**
- Create: `tests/schema/test_read_endpoint_e2e.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`

This task brings the endpoint to life with the success path only. Subsequent tasks layer on tombstones-as-coverage, 404, ETag, and 304.

- [ ] **Step 1: Write the failing tests**

Create `tests/schema/test_read_endpoint_e2e.py`:

```python
from __future__ import annotations

from tests.data.scenarios import ACTIVE_TRUCK_WITH_VIN_FIELD


_T = "t1"  # matches KNOWN_TENANT_IDS and the existing fixture tenant


async def test_get_schema_empty_tenant_returns_zero_version_and_empty_lists(
    client,
) -> None:
    resp = await client.get(f"/schema/{_T}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "schema_version": 0,
        "asset_types": [],
        "maintenance_record_types": [],
    }


async def test_get_schema_returns_seeded_asset_type_with_field(
    client,
) -> None:
    seed_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "payload": {"name": "Truck-read-1"},
        },
    )
    assert seed_resp.status_code in (200, 201), seed_resp.text

    field_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "tenant_id": _T,
            "entity_id": "22222222-2222-2222-2222-222222222222",
            "payload": {
                "parent_id": "11111111-1111-1111-1111-111111111111",
                "name": "VIN",
                "data_type": "text",
            },
        },
    )
    assert field_resp.status_code in (200, 201), field_resp.text

    resp = await client.get(f"/schema/{_T}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] >= 2
    assert body["maintenance_record_types"] == []
    assert len(body["asset_types"]) == 1
    asset_type = body["asset_types"][0]
    assert asset_type["id"] == "11111111-1111-1111-1111-111111111111"
    assert asset_type["name"] == "Truck-read-1"
    assert asset_type["active"] is True
    assert len(asset_type["fields"]) == 1
    field = asset_type["fields"][0]
    assert field == {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "VIN",
        "data_type": "text",
        "validation": None,
        "active": True,
    }
```

The seeding goes through `POST /schema` rather than the `seed`/`load_scenario` fixtures because the e2e `client` uses its own engine (the shared-cache in-memory DB), which the per-test `session` fixture does not reach.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py -v
```

Expected: both tests FAIL with 404 (no route matches `/schema/{tenant_id}` yet — Litestar returns 404 from the router).

- [ ] **Step 3: Implement the handler**

Edit `src/py/novamoc/domain/schema/controllers/_schema.py`. Add imports near the top:

```python
from sqlalchemy import select

import novamoc.db.models as m
from novamoc.config import KNOWN_TENANT_IDS
from novamoc.domain.schema._errors import ErrorCode, TenantNotFoundError
from novamoc.domain.schema._read_payloads import (
    AssetTypeFieldView,
    AssetTypeView,
    MaintenanceRecordTypeFieldView,
    MaintenanceRecordTypeView,
    SchemaSnapshotResponse,
)
```

(Keep the existing `from advanced_alchemy.extensions.litestar import providers` and `from litestar import Controller, post` lines; add `get` to the litestar import.)

```python
from litestar import Controller, get, post
```

Add the new method to `SchemaController` below the existing `post` method:

```python
@get("/{tenant_id:str}")
async def get(
    self,
    tenant_id: str,
    asset_type_service: _services.AssetTypeService,
    asset_type_field_service: _services.AssetTypeFieldService,
    maintenance_record_type_service: _services.MaintenanceRecordTypeService,
    maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
    schema_change_log_service: _services.SchemaChangeLogService,
) -> SchemaSnapshotResponse:
    if tenant_id not in KNOWN_TENANT_IDS:
        raise TenantNotFoundError(
            code=ErrorCode.TENANT_NOT_FOUND, tenant_id=tenant_id
        )

    session = asset_type_service.repository.session

    asset_types = (
        await session.execute(
            select(m.schema.AssetType).where(
                m.schema.AssetType.tenant_id == tenant_id
            )
        )
    ).scalars().all()

    asset_type_fields = (
        await session.execute(
            select(m.schema.AssetTypeField).where(
                m.schema.AssetTypeField.tenant_id == tenant_id
            )
        )
    ).scalars().all()

    record_types = (
        await session.execute(
            select(m.schema.MaintenanceRecordType).where(
                m.schema.MaintenanceRecordType.tenant_id == tenant_id
            )
        )
    ).scalars().all()

    record_type_fields = (
        await session.execute(
            select(m.schema.MaintenanceRecordTypeField).where(
                m.schema.MaintenanceRecordTypeField.tenant_id == tenant_id
            )
        )
    ).scalars().all()

    schema_version = await schema_change_log_service.current_version(
        tenant_id=tenant_id
    )

    fields_by_asset_type: dict[Any, list[AssetTypeFieldView]] = {}
    for f in asset_type_fields:
        fields_by_asset_type.setdefault(f.parent_id, []).append(
            AssetTypeFieldView(
                id=f.id,
                name=f.name,
                data_type=f.data_type,
                validation=f.validation,
                active=f.active,
            )
        )

    fields_by_record_type: dict[Any, list[MaintenanceRecordTypeFieldView]] = {}
    for f in record_type_fields:
        fields_by_record_type.setdefault(f.parent_id, []).append(
            MaintenanceRecordTypeFieldView(
                id=f.id,
                name=f.name,
                data_type=f.data_type,
                validation=f.validation,
                active=f.active,
            )
        )

    return SchemaSnapshotResponse(
        schema_version=schema_version,
        asset_types=tuple(
            AssetTypeView(
                id=t.id,
                name=t.name,
                active=t.active,
                fields=tuple(fields_by_asset_type.get(t.id, ())),
            )
            for t in asset_types
        ),
        maintenance_record_types=tuple(
            MaintenanceRecordTypeView(
                id=t.id,
                name=t.name,
                active=t.active,
                fields=tuple(fields_by_record_type.get(t.id, ())),
            )
            for t in record_types
        ),
    )
```

Add `from typing import Any` to the imports if not already present, and remove the unused `ACTIVE_TRUCK_WITH_VIN_FIELD` import from the test if it isn't being used (the seeding path uses `POST /schema` directly).

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full suite, lint, type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/schema/test_read_endpoint_e2e.py
git commit -m "feat(api): GET /schema/{tenant_id} returns full per-tenant snapshot"
```

---

## Task 7: Verify tombstoned rows are returned with `active: false`

**Files:**
- Modify: `tests/schema/test_read_endpoint_e2e.py`

The handler doesn't filter on `active`, so this should pass without code changes. The test makes that contract explicit.

- [ ] **Step 1: Write the failing test**

Append to `tests/schema/test_read_endpoint_e2e.py`:

```python
async def test_get_schema_includes_tombstoned_rows(client) -> None:
    asset_type_id = "33333333-3333-3333-3333-333333333333"
    field_id = "44444444-4444-4444-4444-444444444444"

    create_t = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": asset_type_id,
            "payload": {"name": "Truck-tombstone"},
        },
    )
    assert create_t.status_code in (200, 201), create_t.text

    create_f = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "tenant_id": _T,
            "entity_id": field_id,
            "payload": {
                "parent_id": asset_type_id,
                "name": "RetiredField",
                "data_type": "text",
            },
        },
    )
    assert create_f.status_code in (200, 201), create_f.text

    deactivate_f = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type_field",
            "tenant_id": _T,
            "entity_id": field_id,
            "payload": {},
        },
    )
    assert deactivate_f.status_code in (200, 201), deactivate_f.text

    deactivate_t = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "tenant_id": _T,
            "entity_id": asset_type_id,
            "payload": {},
        },
    )
    assert deactivate_t.status_code in (200, 201), deactivate_t.text

    resp = await client.get(f"/schema/{_T}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    asset_types_by_id = {t["id"]: t for t in body["asset_types"]}
    truck = asset_types_by_id[asset_type_id]
    assert truck["active"] is False
    fields_by_id = {f["id"]: f for f in truck["fields"]}
    assert fields_by_id[field_id]["active"] is False
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py::test_get_schema_includes_tombstoned_rows -v
```

Expected: PASS — the handler returns every row regardless of `active`, by design.

- [ ] **Step 3: If it does not pass, do not patch around it.** Investigate. The handler must not be filtering on `active`; if it is, remove that filter — the design (and ADR-009) require tombstones to surface.

- [ ] **Step 4: Run the full suite**

```bash
uv run pytest
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/schema/test_read_endpoint_e2e.py
git commit -m "test(api): GET /schema returns tombstoned rows with active: false"
```

---

## Task 8: Add 404 for unknown tenant

**Files:**
- Modify: `tests/schema/test_read_endpoint_e2e.py`

The registry check is already in the handler from Task 6. This test pins the wire shape: status, content-type, problem-details body, and the `tenant_id` extension member.

- [ ] **Step 1: Write the failing test**

Append to `tests/schema/test_read_endpoint_e2e.py`:

```python
async def test_get_schema_unknown_tenant_returns_404_problem_details(client) -> None:
    resp = await client.get("/schema/who-dis")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["type"] == "urn:novamoc:problems:tenant_not_found"
    assert body["title"] == "Tenant not found"
    assert body["tenant_id"] == "who-dis"
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py::test_get_schema_unknown_tenant_returns_404_problem_details -v
```

Expected: PASS — the handler raises `TenantNotFoundError` and the renamed `schema_error_to_problem_details` mapper from Task 2 picks it up.

- [ ] **Step 3: If it fails**, the most likely cause is the `tenant_id` extra not making it through. Confirm `TenantNotFoundError(..., tenant_id=...)` is raised exactly that way (Task 6) and the mapper passes `extra=dict(exc.extras)` (Task 2).

- [ ] **Step 4: Run the full suite**

```bash
uv run pytest
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/schema/test_read_endpoint_e2e.py
git commit -m "test(api): GET /schema returns 404 tenant_not_found for unknown tenant"
```

---

## Task 9: Add the `ETag` header on success responses

**Files:**
- Modify: `tests/schema/test_read_endpoint_e2e.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`

Switch the handler from returning a struct directly to returning a Litestar `Response` so the `ETag` header can be set. Empty tenant gets `ETag: "0"`; populated gets `"<schema_version>"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/schema/test_read_endpoint_e2e.py`:

```python
async def test_get_schema_emits_etag_zero_for_empty_tenant(client) -> None:
    resp = await client.get(f"/schema/{_T}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == '"0"'


async def test_get_schema_emits_etag_matching_schema_version(client) -> None:
    create = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": "55555555-5555-5555-5555-555555555555",
            "payload": {"name": "Truck-etag"},
        },
    )
    assert create.status_code in (200, 201), create.text
    seq = create.json()["schema_version"]

    resp = await client.get(f"/schema/{_T}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == f'"{seq}"'
    assert resp.json()["schema_version"] == seq
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py::test_get_schema_emits_etag_zero_for_empty_tenant tests/schema/test_read_endpoint_e2e.py::test_get_schema_emits_etag_matching_schema_version -v
```

Expected: FAIL — `KeyError: 'etag'` (the header is not set).

- [ ] **Step 3: Add Response import and switch the handler return type**

In `src/py/novamoc/domain/schema/controllers/_schema.py`, update the litestar import:

```python
from litestar import Controller, Response, get, post
```

Change the handler's signature and last `return` to wrap in a `Response`:

```python
@get("/{tenant_id:str}")
async def get(
    self,
    tenant_id: str,
    asset_type_service: _services.AssetTypeService,
    asset_type_field_service: _services.AssetTypeFieldService,
    maintenance_record_type_service: _services.MaintenanceRecordTypeService,
    maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
    schema_change_log_service: _services.SchemaChangeLogService,
) -> Response[SchemaSnapshotResponse]:
    ...  # body unchanged through the projection assembly
    snapshot = SchemaSnapshotResponse(
        schema_version=schema_version,
        asset_types=tuple(...),
        maintenance_record_types=tuple(...),
    )
    return Response(
        content=snapshot,
        headers={"etag": f'"{schema_version}"'},
    )
```

(Keep the body of the handler intact; only the final `return` and the return type annotation change. Don't change Litestar's automatic response handling for the 404 path — that flows through the `ProblemDetailsPlugin` as before.)

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py::test_get_schema_emits_etag_zero_for_empty_tenant tests/schema/test_read_endpoint_e2e.py::test_get_schema_emits_etag_matching_schema_version -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full e2e file to confirm nothing regressed**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py -v
```

Expected: all read-endpoint tests pass (the body assertions still hold because `Response[SchemaSnapshotResponse]` serializes the same way).

- [ ] **Step 6: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/schema/test_read_endpoint_e2e.py
git commit -m "feat(api): emit ETag header on GET /schema responses"
```

---

## Task 10: Honour `If-None-Match` → `304 Not Modified`

**Files:**
- Modify: `tests/schema/test_read_endpoint_e2e.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`

When the request's `If-None-Match` matches the computed `schema_version`, return 304 with the `ETag` header and no body. The version is computed first (cheap MAX(seq) query) so the projection scan is skipped on a hit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/schema/test_read_endpoint_e2e.py`:

```python
async def test_if_none_match_matches_returns_304_with_etag_no_body(client) -> None:
    resp = await client.get(
        f"/schema/{_T}", headers={"If-None-Match": '"0"'}
    )
    assert resp.status_code == 304
    assert resp.headers["etag"] == '"0"'
    assert resp.content == b""


async def test_if_none_match_stale_returns_full_body_with_new_etag(client) -> None:
    create = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "tenant_id": _T,
            "entity_id": "66666666-6666-6666-6666-666666666666",
            "payload": {"name": "Truck-304-stale"},
        },
    )
    assert create.status_code in (200, 201), create.text
    seq = create.json()["schema_version"]

    resp = await client.get(
        f"/schema/{_T}", headers={"If-None-Match": '"0"'}
    )
    assert resp.status_code == 200
    assert resp.headers["etag"] == f'"{seq}"'
    assert resp.json()["schema_version"] == seq


async def test_if_none_match_unknown_tenant_still_returns_404(client) -> None:
    resp = await client.get(
        "/schema/who-dis", headers={"If-None-Match": '"0"'}
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py::test_if_none_match_matches_returns_304_with_etag_no_body tests/schema/test_read_endpoint_e2e.py::test_if_none_match_stale_returns_full_body_with_new_etag tests/schema/test_read_endpoint_e2e.py::test_if_none_match_unknown_tenant_still_returns_404 -v
```

Expected: the first two FAIL (304 path not implemented — request returns 200); the third PASSES (registry check runs before any other logic).

- [ ] **Step 3: Implement the 304 path**

In `src/py/novamoc/domain/schema/controllers/_schema.py`, take a `Request` to read the header, compute the version first, and short-circuit on a match. Add `Request` to the litestar import:

```python
from litestar import Controller, Request, Response, get, post
```

Restructure the handler so the version is computed before the projection scan, and `If-None-Match` is checked between them. Replace the handler body so the order is:

```python
@get("/{tenant_id:str}")
async def get(
    self,
    request: Request,
    tenant_id: str,
    asset_type_service: _services.AssetTypeService,
    asset_type_field_service: _services.AssetTypeFieldService,
    maintenance_record_type_service: _services.MaintenanceRecordTypeService,
    maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
    schema_change_log_service: _services.SchemaChangeLogService,
) -> Response[SchemaSnapshotResponse | None]:
    if tenant_id not in KNOWN_TENANT_IDS:
        raise TenantNotFoundError(
            code=ErrorCode.TENANT_NOT_FOUND, tenant_id=tenant_id
        )

    session = asset_type_service.repository.session

    schema_version = await schema_change_log_service.current_version(
        tenant_id=tenant_id
    )
    etag = f'"{schema_version}"'

    if request.headers.get("if-none-match") == etag:
        return Response(content=None, status_code=304, headers={"etag": etag})

    # ... existing projection-scan + assembly code, unchanged ...

    return Response(content=snapshot, headers={"etag": etag})
```

(Pull `etag = f'"{schema_version}"'` up so the 200 path uses the same string. Keep the rest of the body as it was.)

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py -v
```

Expected: all read-endpoint tests pass.

- [ ] **Step 5: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/schema/test_read_endpoint_e2e.py
git commit -m "feat(api): GET /schema honours If-None-Match → 304 Not Modified"
```

---

## Task 11: Final verification

**Files:** none modified.

- [ ] **Step 1: Run the full Python verification matrix**

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green; total test count includes the new tests added across Tasks 3, 4, 5, 6, 7, 8, 9, 10.

- [ ] **Step 2: Confirm the dev server still starts**

```bash
uv run litestar --app novamoc.asgi:create_app routes
```

Expected: prints the route table including both `POST /schema` and `GET /schema/{tenant_id}`. (Use Ctrl-C if it doesn't return promptly; the `routes` subcommand is non-interactive, but if it ends up running the server, `just serve` is the alternative.)

- [ ] **Step 3: Sanity-check the OpenAPI doc**

```bash
uv run python -c "import json; from novamoc.asgi import create_app; app = create_app(); print(json.dumps(app.openapi_schema.to_schema(), indent=2))" | grep -A2 '"/schema/{tenant_id}"' | head -30
```

Expected: confirms `GET /schema/{tenant_id}` is published with a path parameter and the response schemas are wired.

- [ ] **Step 4: Push the branch**

```bash
git push
```

The PR (#18) updates automatically. Mark it ready for review when the user is satisfied with the diff.

---

## Self-Review

**Spec coverage check:**

- *Route, mounted on existing controller* — Task 6 (`@get("/{tenant_id:str}")` on `SchemaController`).
- *Tenant resolution against `KNOWN_TENANT_IDS`* — Task 1 (constant) + Task 6 (check in handler) + Task 8 (404 wire test).
- *Success response shape (nested, with active flag, no audit columns)* — Task 5 (structs) + Task 6 (handler assembly) + Task 7 (tombstone test).
- *ETag header on every response* — Task 9 (200 emits ETag) + Task 10 (304 emits ETag).
- *If-None-Match → 304* — Task 10.
- *Error envelope (RFC 9457 problem-details, `tenant_not_found`)* — Task 2 (errors + mapper) + Task 3 (mapper unit test) + Task 8 (E2E wire test).
- *Consistency (single read transaction, all five queries)* — Task 6 implements it: a single async session is used for all four projection queries plus the `MAX(seq)` lookup. Task 10 still computes the version inside that session before the optional projection scan; the 304 short-circuit returns inside the same session as well.
- *Pagination — none* — Task 6 (no pagination is implemented; spec says none).
- *Empty tenant returns 200 with `schema_version: 0`* — Task 6 first test.
- *Code surface changes (`config.py`, `_errors.py`, `_problem_details.py`, controller, services, payloads)* — Tasks 1, 2, 4, 5, 6, 9, 10.
- *Tests in `tests/schema/test_read_endpoint_e2e.py` covering empty, populated, 304-fresh, 304-stale, 404, tombstones* — Tasks 6, 7, 8, 9, 10.

No spec requirement is uncovered.

**Placeholder scan:** No "TBD", no "implement later", no "add appropriate error handling". Each step contains the actual code or command needed.

**Type consistency:** `current_version` signature (`tenant_id: str → int`) consistent across Tasks 4 and 6/10. `TenantNotFoundError` constructor (`code=`, `tenant_id=`) consistent across Tasks 2, 3, 6, 8. `SchemaSnapshotResponse` field names (`schema_version`, `asset_types`, `maintenance_record_types`) consistent across Tasks 5, 6, 9, 10. ETag value format (`f'"{schema_version}"'` — quoted integer) consistent across Tasks 9 and 10.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-03-schema-read-endpoint.md`. Ready for execution.
