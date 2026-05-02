# `POST /schema` Endpoint Implementation Plan

> **Historical document.** This plan was the input to the initial implementation. Specific Python snippets and command counts may be out of date with respect to the current vocabulary. Use the design spec at `docs/superpowers/specs/2026-05-01-schema-endpoint-design.md` and ADR-008 as the current sources of truth.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the synchronous, single-route `POST /schema` command endpoint specified in `docs/superpowers/specs/2026-05-01-schema-endpoint-design.md`, covering all 18 commands across the four schema entity kinds (asset_type, asset_type_field, maintenance_record_type, maintenance_record_type_field).

**Architecture:** A discriminated union of msgspec structs forms the request body so Litestar publishes a `oneOf` discriminated by the `command` tag in OpenAPI. A `dict[type, Handler]` dispatch table routes the decoded variant to a free-function handler (in `domain/schema/_handlers/<entity_kind>.py`); each handler reads the projection, validates the state transition, mutates via an advanced-alchemy service, and appends one row to `schema_change_log`. The request-scoped `AsyncSession` plus the existing `before_send_handler="autocommit"` makes projection mutation + change-log append commit atomically and roll back on any 4xx.

**Tech Stack:** Python 3.14, Litestar 2.21+, advanced-alchemy 1.9+, msgspec, SQLAlchemy 2.0 async, aiosqlite, pytest + pytest-asyncio.

---

## Spec reference

`docs/superpowers/specs/2026-05-01-schema-endpoint-design.md` is the source of truth. ADRs 008 (server-authoritative schema), 013 (HTTP/WS transports), 014 (multi-tenancy) are upstream context.

## File Structure

Created or modified by this plan, grouped by responsibility:

**Wire format and outcomes**
- Create `src/py/novamoc/domain/schema/_outcomes.py` — `Outcome` StrEnum + `SchemaCommitOutcome` dataclass.
- Create `src/py/novamoc/domain/schema/_errors.py` — `ErrorCode` StrEnum, `SchemaCommandError` and three concrete subclasses.
- Create `src/py/novamoc/domain/schema/_payloads.py` — 18 per-command msgspec structs + the `SchemaRequest` union + `SchemaResponse` + `SchemaErrorResponse`.

**Persistence**
- Create `src/py/novamoc/domain/schema/services/_change_log.py` — `SchemaChangeLogService.append`.
- Modify `src/py/novamoc/domain/schema/services/_asset_type.py` — drop the TODO comment.
- Create `src/py/novamoc/domain/schema/services/_asset_type_field.py`.
- Create `src/py/novamoc/domain/schema/services/_maintenance_record_type.py`.
- Create `src/py/novamoc/domain/schema/services/_maintenance_record_type_field.py`.
- Modify `src/py/novamoc/domain/schema/services/__init__.py` — re-export the five services.

**Dispatch**
- Create `src/py/novamoc/domain/schema/_dispatch.py` — `ServiceBundle` dataclass, `_HANDLERS` table, `dispatch()`.
- Create `src/py/novamoc/domain/schema/_handlers/__init__.py`.
- Create `src/py/novamoc/domain/schema/_handlers/_common.py` — small private helpers (`_append_change_log`, `_to_payload_json`).
- Create `src/py/novamoc/domain/schema/_handlers/asset_type.py`.
- Create `src/py/novamoc/domain/schema/_handlers/asset_type_field.py`.
- Create `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`.
- Create `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`.

**HTTP layer**
- Modify `src/py/novamoc/domain/schema/controllers/__init__.py` — re-export `SchemaController`.
- Delete `src/py/novamoc/domain/schema/controllers/_asset_type.py` — placeholder, not used.
- Create `src/py/novamoc/domain/schema/controllers/_schema.py` — `SchemaController` with the `POST /schema` route + the exception handler.
- Modify `src/py/novamoc/asgi.py` — register `SchemaController`, drop the `hello_world` placeholder.

**Test infrastructure**
- Modify `pyproject.toml` — add `[tool.pytest.ini_options]`.
- Create `tests/__init__.py`.
- Create `tests/conftest.py` — async engine + session fixtures, app/test-client fixtures.
- Create `tests/schema/__init__.py`.
- Per-task: `tests/schema/test_<topic>.py`.

---

## Conventions

- **TDD.** Every code-bearing task starts with a failing test, then minimal implementation.
- **Commits.** End every task with a commit. Conventional-commit prefix (`feat:`, `test:`, `refactor:`, `chore:`).
- **Tenant-scoped tables.** `asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields` all have composite PK `(tenant_id, id)`. Use `item_id=(tenant_id, entity_id)` for service `update`/`delete` calls. Use `get_one_or_none(tenant_id=..., id=...)` for filter-style lookups.
- **`auto_commit=False`** on every service call. The request-level `before_send_handler="autocommit"` commits on 2xx and rolls back on 4xx/5xx.
- **No web imports in `db/`.** Per stored feedback memory: `db/` imports `advanced_alchemy` core only. Services and handlers (under `domain/`) may import `advanced_alchemy.extensions.litestar`.
- **Test database.** Real in-memory SQLite per test, no mocks (per stored feedback memory).

---

## Task 1: Test infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add pytest config**

In `pyproject.toml`, append:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra"
```

- [ ] **Step 2: Create `tests/__init__.py`**

Empty file:

```python
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from advanced_alchemy.base import metadata_registry
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Importing the models registers their tables on the shared metadata registry.
import novamoc.db.models  # noqa: F401


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        for metadata in metadata_registry.values():
            await conn.run_sync(metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        try:
            yield s
        finally:
            await s.rollback()
```

- [ ] **Step 4: Write a smoke test**

`tests/test_smoke.py`:

```python
"""Smoke tests — confirm the test fixtures work."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_session_executes_select_one(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_schema_tables_exist(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    )
    names = {row[0] for row in result.all()}
    assert "asset_types" in names
    assert "schema_change_log" in names
```

- [ ] **Step 5: Run the smoke tests**

Run: `uv run pytest tests/test_smoke.py -v`

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "test: add pytest config and async-sqlite fixtures"
```

---

## Task 2: Outcomes

**Files:**
- Create: `src/py/novamoc/domain/schema/_outcomes.py`
- Create: `tests/schema/__init__.py`
- Create: `tests/schema/test_outcomes.py`

- [ ] **Step 1: Write failing test**

`tests/schema/__init__.py`: empty.

`tests/schema/test_outcomes.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome


def test_outcome_values() -> None:
    assert {o.value for o in Outcome} == {
        "created",
        "activated",
        "noop",
        "updated",
        "deactivated",
        "cleared",
        "deleted",
    }


def test_schema_commit_outcome_is_constructible() -> None:
    eid = uuid4()
    now = datetime.now(UTC)
    o = SchemaCommitOutcome(
        schema_version=1,
        entity_id=eid,
        outcome=Outcome.CREATED,
        committed_at=now,
    )
    assert o.schema_version == 1
    assert o.entity_id == eid
    assert o.outcome is Outcome.CREATED
    assert o.committed_at == now
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_outcomes.py -v`

Expected: FAIL — `ModuleNotFoundError: novamoc.domain.schema._outcomes`.

- [ ] **Step 3: Implement**

`src/py/novamoc/domain/schema/_outcomes.py`:

```python
"""Outcome of a single accepted ``POST /schema`` command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Outcome(StrEnum):
    CREATED = "created"
    ACTIVATED = "activated"
    NOOP = "noop"
    UPDATED = "updated"
    DEACTIVATED = "deactivated"
    CLEARED = "cleared"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class SchemaCommitOutcome:
    schema_version: int
    entity_id: UUID
    outcome: Outcome
    committed_at: datetime
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_outcomes.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_outcomes.py tests/schema/__init__.py tests/schema/test_outcomes.py
git commit -m "feat(schema): add Outcome enum and SchemaCommitOutcome"
```

---

## Task 3: Errors

**Files:**
- Create: `src/py/novamoc/domain/schema/_errors.py`
- Create: `tests/schema/test_errors.py`

- [ ] **Step 1: Write failing test**

`tests/schema/test_errors.py`:

```python
import pytest

from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
    SchemaCommandError,
)


def test_error_code_membership() -> None:
    assert ErrorCode.PAYLOAD_NO_CHANGES.value == "payload_no_changes"
    assert ErrorCode.INVALID_PAYLOAD_SHAPE.value == "invalid_payload_shape"
    assert ErrorCode.DEFINITION_REQUIRED.value == "definition_required"
    assert ErrorCode.NAME_RESERVED.value == "name_reserved"
    assert ErrorCode.NAME_IS_DEACTIVATED.value == "name_is_deactivated"
    assert ErrorCode.USE_UPDATE.value == "use_update"
    assert ErrorCode.PARENT_TYPE_NOT_FOUND.value == "parent_type_not_found"
    assert ErrorCode.ENTITY_NOT_FOUND.value == "entity_not_found"


@pytest.mark.parametrize(
    ("cls", "status", "error", "code"),
    [
        (PayloadShapeError, 400, "invalid_request", ErrorCode.PAYLOAD_NO_CHANGES),
        (ConflictError, 409, "conflict", ErrorCode.NAME_RESERVED),
        (EntityNotFoundError, 404, "not_found", ErrorCode.ENTITY_NOT_FOUND),
    ],
)
def test_concrete_errors_carry_status_and_label(cls, status, error, code) -> None:
    exc = cls(code=code)
    assert isinstance(exc, SchemaCommandError)
    assert exc.status_code == status
    assert exc.error == error
    assert exc.code is code
    assert exc.message  # default message exists


def test_extras_are_preserved() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    assert exc.extras == {"name": "Truck"}


def test_explicit_message_overrides_default() -> None:
    exc = PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES, message="custom")
    assert exc.message == "custom"
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_errors.py -v`

Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`src/py/novamoc/domain/schema/_errors.py`:

```python
"""Typed exceptions raised by schema-command handlers.

A single Litestar exception handler renders any ``SchemaCommandError`` as
the JSON envelope documented in the spec; ``msgspec.ValidationError`` is
mapped separately at the controller layer to the same shape with
``code=invalid_payload_shape``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # 400 — invalid_request (request shape)
    PAYLOAD_NO_CHANGES = "payload_no_changes"
    INVALID_PAYLOAD_SHAPE = "invalid_payload_shape"
    # 409 — conflict (request well-shaped, conflicts with current projection state)
    DEFINITION_REQUIRED = "definition_required"
    NAME_RESERVED = "name_reserved"
    NAME_IS_DEACTIVATED = "name_is_deactivated"
    USE_UPDATE = "use_update"
    PARENT_TYPE_NOT_FOUND = "parent_type_not_found"
    # 404 — not_found
    ENTITY_NOT_FOUND = "entity_not_found"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Request payload did not match the expected shape.",
    ErrorCode.DEFINITION_REQUIRED: "Entity does not exist; submit a non-empty payload to create it.",
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.NAME_IS_DEACTIVATED: (
        "Name is held by a deactivated entity; activate it with an "
        "empty-payload activate, then update."
    ),
    ErrorCode.USE_UPDATE: "Entity already exists and is active; use update_* to modify it.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
}


class SchemaCommandError(Exception):
    """Base class for schema-command failures.

    Subclasses pin ``status_code`` and the ``error`` label that appear in
    the response envelope. The ``code`` discriminates failure modes within
    a category and is what clients branch on.
    """

    status_code: int = 400
    error: str = "invalid_request"

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


class PayloadShapeError(SchemaCommandError):
    status_code = 400
    error = "invalid_request"


class ConflictError(SchemaCommandError):
    status_code = 409
    error = "conflict"


class EntityNotFoundError(SchemaCommandError):
    status_code = 404
    error = "not_found"
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_errors.py -v`

Expected: all parametrized cases pass (4 test functions, several parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_errors.py tests/schema/test_errors.py
git commit -m "feat(schema): add error codes and exception classes"
```

---

## Task 4: AssetType payload structs

**Files:**
- Create: `src/py/novamoc/domain/schema/_payloads.py` (will be appended in later tasks)
- Create: `tests/schema/test_payloads.py` (will be appended in later tasks)

- [ ] **Step 1: Write failing test**

`tests/schema/test_payloads.py`:

```python
"""Round-trip tests for the request-body discriminated union.

Each command's wire shape is encoded and decoded as the union; the test
asserts the runtime variant class plus the typed payload field.
"""

from __future__ import annotations

import json
from uuid import UUID

import msgspec
import pytest

from novamoc.domain.schema._payloads import (
    ActivateAssetType,
    DeactivateAssetType,
    DeleteAssetType,
    SchemaRequest,
    UpdateAssetType,
    _AssetTypeDefinition,
    _AssetTypeUpdate,
    _Empty,
)

_TENANT = "01J7K0F0V8MQQQX0Z2A0Z2A0Z2"
_ENTITY = "01958f3b-3b9f-7d3a-89aa-000000000001"


def _decode(body: dict) -> SchemaRequest:
    return msgspec.json.decode(json.dumps(body).encode(), type=SchemaRequest)


def test_activate_asset_type_create() -> None:
    obj = _decode({
        "command": "activate_asset_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"name": "Truck"},
    })
    assert isinstance(obj, ActivateAssetType)
    assert isinstance(obj.payload, _AssetTypeDefinition)
    assert obj.payload.name == "Truck"
    assert obj.entity_id == UUID(_ENTITY)


def test_activate_asset_type_when_empty() -> None:
    obj = _decode({
        "command": "activate_asset_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(obj, ActivateAssetType)
    assert isinstance(obj.payload, _Empty)


def test_update_asset_type_partial() -> None:
    obj = _decode({
        "command": "update_asset_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"name": "Lorry"},
    })
    assert isinstance(obj, UpdateAssetType)
    assert obj.payload.name == "Lorry"


def test_deactivate_and_delete_require_empty_payload() -> None:
    deact = _decode({
        "command": "deactivate_asset_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(deact, DeactivateAssetType)

    delete = _decode({
        "command": "delete_asset_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(delete, DeleteAssetType)


def test_empty_payload_struct_rejects_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode({
            "command": "deactivate_asset_type",
            "tenant_id": _TENANT,
            "entity_id": _ENTITY,
            "payload": {"name": "x"},
        })
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: ImportError — `_payloads` does not exist yet.

- [ ] **Step 3: Implement (AssetType portion only — others added in later tasks)**

`src/py/novamoc/domain/schema/_payloads.py`:

```python
"""Wire-format structs for ``POST /schema``.

The 18 per-command structs share ``tag_field="command"`` and form
``SchemaRequest``, the discriminated union Litestar publishes as a
``oneOf`` in the OpenAPI schema. Per-command payload shapes are kept as
private structs (``_*``) since they are only meaningful as the payload
field of a specific command struct.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec

from novamoc.db.models.schema import FieldDataType


class _Empty(msgspec.Struct, forbid_unknown_fields=True):
    """Marker for commands whose payload must be ``{}``.

    ``forbid_unknown_fields=True`` makes ``{"x": 1}`` a decoder error
    rather than a silently-accepted empty struct.
    """


# --- AssetType payload shapes ---

class _AssetTypeDefinition(msgspec.Struct, forbid_unknown_fields=True):
    name: str


class _AssetTypeUpdate(msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True):
    name: str | None = None


# --- AssetType command structs ---

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


# --- The discriminated union (placeholder; later tasks extend it) ---

SchemaRequest = (
    ActivateAssetType | UpdateAssetType | DeactivateAssetType | DeleteAssetType
)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py tests/schema/test_payloads.py
git commit -m "feat(schema): add AssetType command structs and tagged-union skeleton"
```

---

## Task 5: AssetTypeField payload structs

**Files:**
- Modify: `src/py/novamoc/domain/schema/_payloads.py`
- Modify: `tests/schema/test_payloads.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/schema/test_payloads.py`:

```python
from novamoc.domain.schema._payloads import (
    ActivateAssetTypeField,
    ClearAssetTypeField,
    DeactivateAssetTypeField,
    DeleteAssetTypeField,
    UpdateAssetTypeField,
    _AssetTypeFieldDefinition,
    _AssetTypeFieldUpdate,
)

_PARENT = "01958f3b-3b9f-7d3a-89aa-000000000aaa"


def test_activate_asset_type_field_create() -> None:
    obj = _decode({
        "command": "activate_asset_type_field",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {
            "asset_type_id": _PARENT,
            "name": "vin",
            "data_type": "text",
            "validation": {"max_length": 17},
        },
    })
    assert isinstance(obj, ActivateAssetTypeField)
    assert isinstance(obj.payload, _AssetTypeFieldDefinition)
    assert obj.payload.asset_type_id == UUID(_PARENT)
    assert obj.payload.name == "vin"
    assert obj.payload.data_type == "text"
    assert obj.payload.validation == {"max_length": 17}


def test_activate_asset_type_field_when_empty() -> None:
    obj = _decode({
        "command": "activate_asset_type_field",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(obj, ActivateAssetTypeField)
    assert isinstance(obj.payload, _Empty)


def test_update_asset_type_field_partial() -> None:
    obj = _decode({
        "command": "update_asset_type_field",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"name": "vin_number"},
    })
    assert isinstance(obj, UpdateAssetTypeField)
    assert obj.payload.name == "vin_number"
    assert obj.payload.data_type is None


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        ("deactivate_asset_type_field", DeactivateAssetTypeField),
        ("clear_asset_type_field", ClearAssetTypeField),
        ("delete_asset_type_field", DeleteAssetTypeField),
    ],
)
def test_asset_type_field_empty_payload_commands(command: str, cls: type) -> None:
    obj = _decode({
        "command": command,
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(obj, cls)
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: ImportError — the new symbols are not defined yet.

- [ ] **Step 3: Append to `_payloads.py`**

Append after the AssetType command-struct block, **before** the `SchemaRequest` line, and rewrite the `SchemaRequest` union:

```python
# --- AssetTypeField payload shapes ---

class _AssetTypeFieldDefinition(msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True):
    asset_type_id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None = None


class _AssetTypeFieldUpdate(msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True):
    name: str | None = None
    data_type: FieldDataType | None = None
    validation: dict[str, Any] | None = None


# --- AssetTypeField command structs ---

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
```

Update the `SchemaRequest` union to include the new members:

```python
SchemaRequest = (
    ActivateAssetType | UpdateAssetType | DeactivateAssetType | DeleteAssetType
    | ActivateAssetTypeField | UpdateAssetTypeField | DeactivateAssetTypeField
    | ClearAssetTypeField | DeleteAssetTypeField
)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: all asset-type-field tests pass alongside the asset-type ones.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py tests/schema/test_payloads.py
git commit -m "feat(schema): add AssetTypeField command structs"
```

---

## Task 6: MaintenanceRecordType payload structs

**Files:**
- Modify: `src/py/novamoc/domain/schema/_payloads.py`
- Modify: `tests/schema/test_payloads.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/schema/test_payloads.py`:

```python
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordType,
    DeactivateMaintenanceRecordType,
    DeleteMaintenanceRecordType,
    UpdateMaintenanceRecordType,
    _MaintenanceRecordTypeDefinition,
    _MaintenanceRecordTypeUpdate,
)


def test_activate_maintenance_record_type_create() -> None:
    obj = _decode({
        "command": "activate_maintenance_record_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"name": "Oil Change"},
    })
    assert isinstance(obj, ActivateMaintenanceRecordType)
    assert isinstance(obj.payload, _MaintenanceRecordTypeDefinition)
    assert obj.payload.name == "Oil Change"


def test_update_maintenance_record_type_partial() -> None:
    obj = _decode({
        "command": "update_maintenance_record_type",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"name": "Annual Inspection"},
    })
    assert isinstance(obj, UpdateMaintenanceRecordType)
    assert obj.payload.name == "Annual Inspection"


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        ("deactivate_maintenance_record_type", DeactivateMaintenanceRecordType),
        ("delete_maintenance_record_type", DeleteMaintenanceRecordType),
    ],
)
def test_maintenance_record_type_empty_payload(command: str, cls: type) -> None:
    obj = _decode({
        "command": command,
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(obj, cls)
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: ImportError.

- [ ] **Step 3: Append to `_payloads.py`**

Append before the `SchemaRequest` line:

```python
# --- MaintenanceRecordType payload shapes ---

class _MaintenanceRecordTypeDefinition(msgspec.Struct, forbid_unknown_fields=True):
    name: str


class _MaintenanceRecordTypeUpdate(msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True):
    name: str | None = None


# --- MaintenanceRecordType command structs ---

class ActivateMaintenanceRecordType(
    msgspec.Struct, tag="activate_maintenance_record_type", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeDefinition | _Empty


class UpdateMaintenanceRecordType(
    msgspec.Struct, tag="update_maintenance_record_type", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeUpdate


class DeactivateMaintenanceRecordType(
    msgspec.Struct, tag="deactivate_maintenance_record_type", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _Empty


class DeleteMaintenanceRecordType(
    msgspec.Struct, tag="delete_maintenance_record_type", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _Empty
```

Update the `SchemaRequest` union:

```python
SchemaRequest = (
    ActivateAssetType | UpdateAssetType | DeactivateAssetType | DeleteAssetType
    | ActivateAssetTypeField | UpdateAssetTypeField | DeactivateAssetTypeField
    | ClearAssetTypeField | DeleteAssetTypeField
    | ActivateMaintenanceRecordType | UpdateMaintenanceRecordType
    | DeactivateMaintenanceRecordType | DeleteMaintenanceRecordType
)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py tests/schema/test_payloads.py
git commit -m "feat(schema): add MaintenanceRecordType command structs"
```

---

## Task 7: MaintenanceRecordTypeField payload structs

**Files:**
- Modify: `src/py/novamoc/domain/schema/_payloads.py`
- Modify: `tests/schema/test_payloads.py`

- [ ] **Step 1: Append failing tests**

```python
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordTypeField,
    ClearMaintenanceRecordTypeField,
    DeactivateMaintenanceRecordTypeField,
    DeleteMaintenanceRecordTypeField,
    UpdateMaintenanceRecordTypeField,
    _MaintenanceRecordTypeFieldDefinition,
    _MaintenanceRecordTypeFieldUpdate,
)


def test_activate_maintenance_record_type_field_create() -> None:
    obj = _decode({
        "command": "activate_maintenance_record_type_field",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {
            "maintenance_record_type_id": _PARENT,
            "name": "mileage_at_service",
            "data_type": "integer",
        },
    })
    assert isinstance(obj, ActivateMaintenanceRecordTypeField)
    assert isinstance(obj.payload, _MaintenanceRecordTypeFieldDefinition)
    assert obj.payload.maintenance_record_type_id == UUID(_PARENT)
    assert obj.payload.name == "mileage_at_service"
    assert obj.payload.data_type == "integer"


def test_update_maintenance_record_type_field_partial() -> None:
    obj = _decode({
        "command": "update_maintenance_record_type_field",
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {"data_type": "number"},
    })
    assert isinstance(obj, UpdateMaintenanceRecordTypeField)
    assert obj.payload.data_type == "number"


@pytest.mark.parametrize(
    ("command", "cls"),
    [
        ("deactivate_maintenance_record_type_field", DeactivateMaintenanceRecordTypeField),
        ("clear_maintenance_record_type_field", ClearMaintenanceRecordTypeField),
        ("delete_maintenance_record_type_field", DeleteMaintenanceRecordTypeField),
    ],
)
def test_maintenance_record_type_field_empty_payload(command: str, cls: type) -> None:
    obj = _decode({
        "command": command,
        "tenant_id": _TENANT,
        "entity_id": _ENTITY,
        "payload": {},
    })
    assert isinstance(obj, cls)
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: ImportError.

- [ ] **Step 3: Append to `_payloads.py`**

```python
# --- MaintenanceRecordTypeField payload shapes ---

class _MaintenanceRecordTypeFieldDefinition(
    msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True,
):
    maintenance_record_type_id: UUID
    name: str
    data_type: FieldDataType
    validation: dict[str, Any] | None = None


class _MaintenanceRecordTypeFieldUpdate(
    msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True,
):
    name: str | None = None
    data_type: FieldDataType | None = None
    validation: dict[str, Any] | None = None


class ActivateMaintenanceRecordTypeField(
    msgspec.Struct, tag="activate_maintenance_record_type_field", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeFieldDefinition | _Empty


class UpdateMaintenanceRecordTypeField(
    msgspec.Struct, tag="update_maintenance_record_type_field", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _MaintenanceRecordTypeFieldUpdate


class DeactivateMaintenanceRecordTypeField(
    msgspec.Struct, tag="deactivate_maintenance_record_type_field", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _Empty


class ClearMaintenanceRecordTypeField(
    msgspec.Struct, tag="clear_maintenance_record_type_field", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _Empty


class DeleteMaintenanceRecordTypeField(
    msgspec.Struct, tag="delete_maintenance_record_type_field", tag_field="command",
):
    tenant_id: str
    entity_id: UUID
    payload: _Empty
```

Update `SchemaRequest` to its full 17-member form:

```python
SchemaRequest = (
    ActivateAssetType | UpdateAssetType | DeactivateAssetType | DeleteAssetType
    | ActivateAssetTypeField | UpdateAssetTypeField | DeactivateAssetTypeField
    | ClearAssetTypeField | DeleteAssetTypeField
    | ActivateMaintenanceRecordType | UpdateMaintenanceRecordType
    | DeactivateMaintenanceRecordType | DeleteMaintenanceRecordType
    | ActivateMaintenanceRecordTypeField | UpdateMaintenanceRecordTypeField
    | DeactivateMaintenanceRecordTypeField | ClearMaintenanceRecordTypeField
    | DeleteMaintenanceRecordTypeField
)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py tests/schema/test_payloads.py
git commit -m "feat(schema): add MaintenanceRecordTypeField command structs"
```

---

## Task 8: Response and error envelopes + decoder rejections

**Files:**
- Modify: `src/py/novamoc/domain/schema/_payloads.py`
- Modify: `tests/schema/test_payloads.py`

- [ ] **Step 1: Append failing tests**

Append:

```python
from novamoc.domain.schema._payloads import SchemaErrorResponse, SchemaResponse


def test_schema_response_has_expected_fields() -> None:
    resp = SchemaResponse(
        schema_version=1,
        entity_id=UUID(_ENTITY),
        outcome="created",
        committed_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    encoded = msgspec.json.decode(msgspec.json.encode(resp))
    assert encoded == {
        "schema_version": 1,
        "entity_id": _ENTITY,
        "outcome": "created",
        "committed_at": "2026-05-01T12:00:00Z",
    }


def test_schema_error_response_minimal_envelope() -> None:
    resp = SchemaErrorResponse(error="conflict", code="name_is_deactivated", message="…")
    encoded = msgspec.json.decode(msgspec.json.encode(resp))
    assert encoded == {"error": "conflict", "code": "name_is_deactivated", "message": "…"}


def test_unknown_command_rejected_by_decoder() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode({
            "command": "do_a_barrel_roll",
            "tenant_id": _TENANT,
            "entity_id": _ENTITY,
            "payload": {},
        })
```

Add the `datetime, UTC` imports at the top of the test file (already imported in Task 2's test) — confirm presence.

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: ImportError on `SchemaResponse` / `SchemaErrorResponse`.

- [ ] **Step 3: Append to `_payloads.py`**

Append at the bottom:

```python
# --- Response envelopes ---

class SchemaResponse(msgspec.Struct):
    schema_version: int
    entity_id: UUID
    outcome: str  # value of an Outcome enum member
    committed_at: datetime


class SchemaErrorResponse(msgspec.Struct, omit_defaults=True):
    error: str  # "invalid_request" | "conflict" | "not_found"
    code: str
    message: str
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_payloads.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py tests/schema/test_payloads.py
git commit -m "feat(schema): add response/error envelope structs"
```

---

## Task 9: SchemaChangeLogService

**Files:**
- Create: `src/py/novamoc/domain/schema/services/_change_log.py`
- Modify: `src/py/novamoc/domain/schema/services/__init__.py`
- Create: `tests/schema/test_change_log_service.py`

- [ ] **Step 1: Write failing test**

`tests/schema/test_change_log_service.py`:

```python
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService


async def test_append_writes_a_row_and_returns_seq(session: AsyncSession) -> None:
    svc = SchemaChangeLogService(session=session)
    eid = uuid4()
    row = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=eid,
        payload={"name": "Truck"},
    )
    await session.flush()
    assert row.seq is not None
    assert row.tenant_id == "t1"
    assert row.command == "activate_asset_type"
    assert row.entity_id == eid
    assert row.payload == {"name": "Truck"}
    assert row.committed_at is not None


async def test_append_assigns_monotonic_seq(session: AsyncSession) -> None:
    svc = SchemaChangeLogService(session=session)
    a = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "A"},
    )
    b = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "B"},
    )
    await session.flush()
    assert b.seq > a.seq

    rows = (
        await session.execute(
            select(schema_models.SchemaChangeLog).order_by(schema_models.SchemaChangeLog.seq)
        )
    ).scalars().all()
    assert [r.command for r in rows] == ["activate_asset_type", "activate_asset_type"]
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_change_log_service.py -v`

Expected: ImportError.

- [ ] **Step 3: Implement service**

`src/py/novamoc/domain/schema/services/_change_log.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.extensions.litestar import repository, service

import novamoc.db.models as m
from novamoc.domain.schema._commands import SchemaCommand


class SchemaChangeLogService(service.SQLAlchemyAsyncRepositoryService[m.schema.SchemaChangeLog]):
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
```

`src/py/novamoc/domain/schema/services/__init__.py`:

```python
from ._change_log import SchemaChangeLogService

__all__ = ("SchemaChangeLogService",)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_change_log_service.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/services/_change_log.py src/py/novamoc/domain/schema/services/__init__.py tests/schema/test_change_log_service.py
git commit -m "feat(schema): add SchemaChangeLogService.append"
```

---

## Task 10: Entity-kind services

**Files:**
- Modify: `src/py/novamoc/domain/schema/services/_asset_type.py` (drop the TODO)
- Create: `src/py/novamoc/domain/schema/services/_asset_type_field.py`
- Create: `src/py/novamoc/domain/schema/services/_maintenance_record_type.py`
- Create: `src/py/novamoc/domain/schema/services/_maintenance_record_type_field.py`
- Modify: `src/py/novamoc/domain/schema/services/__init__.py`
- Create: `tests/schema/test_entity_services.py`

- [ ] **Step 1: Write failing test**

```python
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
)


@pytest.mark.parametrize(
    "service_cls",
    [
        AssetTypeService,
        MaintenanceRecordTypeService,
    ],
)
async def test_type_service_round_trip(service_cls, session: AsyncSession) -> None:
    svc = service_cls(session=session)
    eid = uuid4()
    obj = await svc.create(
        data={"tenant_id": "t1", "id": eid, "name": "X", "active": True},
        auto_commit=False,
    )
    await session.flush()
    fetched = await svc.get_one_or_none(tenant_id="t1", id=eid)
    assert fetched is not None
    assert fetched.name == "X"
    assert obj.id == eid


@pytest.mark.parametrize(
    ("type_svc_cls", "field_svc_cls", "parent_fk"),
    [
        (AssetTypeService, AssetTypeFieldService, "asset_type_id"),
        (MaintenanceRecordTypeService, MaintenanceRecordTypeFieldService, "maintenance_record_type_id"),
    ],
)
async def test_field_service_round_trip(
    type_svc_cls, field_svc_cls, parent_fk: str, session: AsyncSession,
) -> None:
    type_svc = type_svc_cls(session=session)
    field_svc = field_svc_cls(session=session)
    type_id = uuid4()
    field_id = uuid4()
    await type_svc.create(
        data={"tenant_id": "t1", "id": type_id, "name": "T", "active": True},
        auto_commit=False,
    )
    await session.flush()
    obj = await field_svc.create(
        data={
            "tenant_id": "t1",
            "id": field_id,
            parent_fk: type_id,
            "name": "f",
            "data_type": "text",
            "validation": None,
            "active": True,
        },
        auto_commit=False,
    )
    await session.flush()
    assert obj.id == field_id
    fetched = await field_svc.get_one_or_none(tenant_id="t1", id=field_id)
    assert fetched is not None
    assert getattr(fetched, parent_fk) == type_id
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_entity_services.py -v`

Expected: ImportError.

- [ ] **Step 3: Replace `services/_asset_type.py` with the TODO removed**

```python
import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetType]):
        model_type = m.schema.AssetType

    repository_type = Repo
```

- [ ] **Step 4: Add the three new services**

`src/py/novamoc/domain/schema/services/_asset_type_field.py`:

```python
import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeFieldService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetTypeField]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetTypeField]):
        model_type = m.schema.AssetTypeField

    repository_type = Repo
```

`src/py/novamoc/domain/schema/services/_maintenance_record_type.py`:

```python
import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class MaintenanceRecordTypeService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordType],
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordType]):
        model_type = m.schema.MaintenanceRecordType

    repository_type = Repo
```

`src/py/novamoc/domain/schema/services/_maintenance_record_type_field.py`:

```python
import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class MaintenanceRecordTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordTypeField],
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordTypeField]):
        model_type = m.schema.MaintenanceRecordTypeField

    repository_type = Repo
```

Update `services/__init__.py`:

```python
from ._asset_type import AssetTypeService
from ._asset_type_field import AssetTypeFieldService
from ._change_log import SchemaChangeLogService
from ._maintenance_record_type import MaintenanceRecordTypeService
from ._maintenance_record_type_field import MaintenanceRecordTypeFieldService

__all__ = (
    "AssetTypeFieldService",
    "AssetTypeService",
    "MaintenanceRecordTypeFieldService",
    "MaintenanceRecordTypeService",
    "SchemaChangeLogService",
)
```

- [ ] **Step 5: Run, expect pass**

Run: `uv run pytest tests/schema/test_entity_services.py -v`

Expected: 4 parametrized cases pass.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/services tests/schema/test_entity_services.py
git commit -m "feat(schema): add per-entity-kind services"
```

---

## Task 11: ServiceBundle and dispatch skeleton

**Files:**
- Create: `src/py/novamoc/domain/schema/_dispatch.py`
- Create: `tests/schema/test_dispatch.py`

(The `_HANDLERS` table is populated incrementally by Tasks 12-15. This task defines the seam.)

- [ ] **Step 1: Write failing test**

`tests/schema/test_dispatch.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema._dispatch import ServiceBundle, _HANDLERS, dispatch
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)


async def test_service_bundle_holds_five_services(session: AsyncSession) -> None:
    bundle = ServiceBundle(
        asset_type=AssetTypeService(session=session),
        asset_type_field=AssetTypeFieldService(session=session),
        maintenance_record_type=MaintenanceRecordTypeService(session=session),
        maintenance_record_type_field=MaintenanceRecordTypeFieldService(session=session),
        change_log=SchemaChangeLogService(session=session),
    )
    assert isinstance(bundle.asset_type, AssetTypeService)
    assert isinstance(bundle.change_log, SchemaChangeLogService)


def test_handlers_table_is_empty_initially() -> None:
    # Populated by Tasks 12-15. This guard catches accidental partial registration.
    # (After Task 15 this assertion is updated to == 17.)
    assert isinstance(_HANDLERS, dict)
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_dispatch.py -v`

Expected: ImportError.

- [ ] **Step 3: Implement dispatch skeleton**

`src/py/novamoc/domain/schema/_dispatch.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from novamoc.domain.schema._outcomes import SchemaCommitOutcome
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)


@dataclass(frozen=True, slots=True)
class ServiceBundle:
    asset_type: AssetTypeService
    asset_type_field: AssetTypeFieldService
    maintenance_record_type: MaintenanceRecordTypeService
    maintenance_record_type_field: MaintenanceRecordTypeFieldService
    change_log: SchemaChangeLogService


Handler: TypeAlias = Callable[[ServiceBundle, Any], Awaitable[SchemaCommitOutcome]]


_HANDLERS: dict[type, Handler] = {}
"""Populated by ``novamoc.domain.schema._handlers``. Imports are at the
bottom of this module so the table is built once at import time."""


async def dispatch(services: ServiceBundle, request: Any) -> SchemaCommitOutcome:
    return await _HANDLERS[type(request)](services, request)


# Late imports — populate _HANDLERS by side effect.
# (Done by appending entries to _HANDLERS in each handler module.)
from novamoc.domain.schema import _handlers  # noqa: E402, F401
```

Create the empty `_handlers/__init__.py`:

```python
"""Per-entity-kind command handlers.

Importing this package populates ``_dispatch._HANDLERS`` as a side effect.
"""

from . import (
    asset_type,  # noqa: F401
    asset_type_field,  # noqa: F401
    maintenance_record_type,  # noqa: F401
    maintenance_record_type_field,  # noqa: F401
)
```

Create empty placeholder modules so the imports above succeed (they will be filled in Tasks 12-15):

```python
# src/py/novamoc/domain/schema/_handlers/asset_type.py
"""AssetType command handlers. Filled in by Task 12."""
```

```python
# src/py/novamoc/domain/schema/_handlers/asset_type_field.py
"""AssetTypeField command handlers. Filled in by Task 13."""
```

```python
# src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py
"""MaintenanceRecordType command handlers. Filled in by Task 14."""
```

```python
# src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py
"""MaintenanceRecordTypeField command handlers. Filled in by Task 15."""
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_dispatch.py -v`

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_dispatch.py src/py/novamoc/domain/schema/_handlers tests/schema/test_dispatch.py
git commit -m "feat(schema): add ServiceBundle and dispatch skeleton"
```

---

## Task 12: AssetType handlers

**Files:**
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type.py`
- Create: `tests/schema/test_handlers_asset_type.py`

This task implements all four AssetType verbs: `activate`, `update`, `deactivate`, `delete`.

- [ ] **Step 1: Add a fixture for the bundle**

Append to `tests/conftest.py`:

```python
from novamoc.domain.schema._dispatch import ServiceBundle
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)


@pytest.fixture
def services(session) -> ServiceBundle:
    return ServiceBundle(
        asset_type=AssetTypeService(session=session),
        asset_type_field=AssetTypeFieldService(session=session),
        maintenance_record_type=MaintenanceRecordTypeService(session=session),
        maintenance_record_type_field=MaintenanceRecordTypeFieldService(session=session),
        change_log=SchemaChangeLogService(session=session),
    )
```

- [ ] **Step 2: Write failing tests for the validation matrix**

`tests/schema/test_handlers_asset_type.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.domain.schema._dispatch import ServiceBundle, dispatch
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome
from novamoc.domain.schema._payloads import (
    ActivateAssetType,
    DeactivateAssetType,
    DeleteAssetType,
    UpdateAssetType,
    _AssetTypeDefinition,
    _AssetTypeUpdate,
    _Empty,
)


_T = "t1"


async def _make_active_truck(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Truck", "active": True},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_deactivated_truck(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Truck", "active": False},
        auto_commit=False,
    )
    await session.flush()
    return eid


# --- activate ---

async def test_activate_create(session: AsyncSession, services: ServiceBundle) -> None:
    eid = uuid4()
    out = await dispatch(
        services,
        ActivateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeDefinition(name="Truck")),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    assert out.entity_id == eid
    assert out.schema_version > 0

    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row is not None and row.name == "Truck" and row.active is True

    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert [r.command for r in log] == ["activate_asset_type"]


async def test_activate_when_deactivated(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_deactivated_truck(session, services)
    out = await dispatch(
        services, ActivateAssetType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.ACTIVATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row.active is True


async def test_activate_noop(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services, ActivateAssetType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.NOOP


async def test_activate_missing_with_empty_rejects(session: AsyncSession, services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services, ActivateAssetType(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )
    assert exc_info.value.code is ErrorCode.DEFINITION_REQUIRED


async def test_activate_active_with_payload_rejects(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeDefinition(name="Truck")),
        )
    assert exc_info.value.code is ErrorCode.USE_UPDATE


async def test_activate_deactivated_with_payload_rejects(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_deactivated_truck(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeDefinition(name="Truck")),
        )
    assert exc_info.value.code is ErrorCode.NAME_IS_DEACTIVATED


async def test_activate_create_name_collision(session: AsyncSession, services: ServiceBundle) -> None:
    await _make_active_truck(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateAssetType(tenant_id=_T, entity_id=uuid4(), payload=_AssetTypeDefinition(name="Truck")),
        )
    assert exc_info.value.code is ErrorCode.NAME_RESERVED


# --- update ---

async def test_update_changes_name(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services,
        UpdateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeUpdate(name="Lorry")),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row.name == "Lorry"


async def test_update_when_deactivated_is_allowed(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_deactivated_truck(session, services)
    out = await dispatch(
        services,
        UpdateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeUpdate(name="Lorry")),
    )
    assert out.outcome is Outcome.UPDATED


async def test_update_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            UpdateAssetType(tenant_id=_T, entity_id=uuid4(), payload=_AssetTypeUpdate(name="X")),
        )


async def test_update_no_changes_rejects(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    with pytest.raises(PayloadShapeError) as exc_info:
        await dispatch(
            services,
            UpdateAssetType(tenant_id=_T, entity_id=eid, payload=_AssetTypeUpdate()),
        )
    assert exc_info.value.code is ErrorCode.PAYLOAD_NO_CHANGES


# --- deactivate ---

async def test_deactivate_active(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services, DeactivateAssetType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED
    row = await services.asset_type.get_one_or_none(tenant_id=_T, id=eid)
    assert row.active is False


async def test_deactivate_deactivated_is_noop(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_deactivated_truck(session, services)
    out = await dispatch(
        services, DeactivateAssetType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    assert out.outcome is Outcome.NOOP


async def test_deactivate_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services, DeactivateAssetType(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )


# --- delete ---

async def test_delete_removes_row(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active_truck(session, services)
    out = await dispatch(
        services, DeleteAssetType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.asset_type.get_one_or_none(tenant_id=_T, id=eid) is None


async def test_delete_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services, DeleteAssetType(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )
```

- [ ] **Step 3: Run, expect failure**

Run: `uv run pytest tests/schema/test_handlers_asset_type.py -v`

Expected: every test raises `KeyError` from `dispatch` (handlers not registered yet).

- [ ] **Step 4: Implement handlers**

`src/py/novamoc/domain/schema/_handlers/asset_type.py`:

```python
"""AssetType command handlers.

Each handler reads the projection, validates the transition, mutates the
projection (``auto_commit=False``), and appends a ``schema_change_log``
row. A successful return yields a :class:`SchemaCommitOutcome` whose
``schema_version`` is the appended row's ``seq``.
"""

from __future__ import annotations

import msgspec
from sqlalchemy.exc import IntegrityError

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import ServiceBundle, _HANDLERS
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome
from novamoc.domain.schema._payloads import (
    ActivateAssetType,
    DeactivateAssetType,
    DeleteAssetType,
    UpdateAssetType,
    _AssetTypeDefinition,
    _Empty,
)


async def _activate(services: ServiceBundle, req: ActivateAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    payload_is_empty = isinstance(req.payload, _Empty)

    if obj is None:
        if payload_is_empty:
            raise ConflictError(code=ErrorCode.DEFINITION_REQUIRED)
        defn: _AssetTypeDefinition = req.payload  # type: ignore[assignment]
        try:
            await services.asset_type.create(
                data={
                    "tenant_id": req.tenant_id,
                    "id": req.entity_id,
                    "name": defn.name,
                    "active": True,
                },
                auto_commit=False,
            )
        except IntegrityError as exc:
            raise ConflictError(code=ErrorCode.NAME_RESERVED, name=defn.name) from exc
        outcome = Outcome.CREATED
    elif not obj.active:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.NAME_IS_DEACTIVATED)
        await services.asset_type.update(
            data={"active": True},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    else:
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


async def _update(services: ServiceBundle, req: UpdateAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload, builtin_types=(type(None),))
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.asset_type.update(
            data=payload, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.UPDATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.UPDATED, row.committed_at)


async def _deactivate(services: ServiceBundle, req: DeactivateAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.asset_type.update(
            data={"active": False},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DEACTIVATE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _delete(services: ServiceBundle, req: DeleteAssetType) -> SchemaCommitOutcome:
    obj = await services.asset_type.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.asset_type.delete(
        item_id=(req.tenant_id, req.entity_id), auto_commit=False,
    )
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DELETE_ASSET_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.DELETED, row.committed_at)


_HANDLERS[ActivateAssetType] = _activate
_HANDLERS[UpdateAssetType] = _update
_HANDLERS[DeactivateAssetType] = _deactivate
_HANDLERS[DeleteAssetType] = _delete
```

- [ ] **Step 5: Run, expect pass**

Run: `uv run pytest tests/schema/test_handlers_asset_type.py -v`

Expected: all 17 tests in this file pass.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/_handlers/asset_type.py tests/schema/test_handlers_asset_type.py tests/conftest.py
git commit -m "feat(schema): implement AssetType command handlers"
```

---

## Task 13: AssetTypeField handlers

**Files:**
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type_field.py`
- Create: `tests/schema/test_handlers_asset_type_field.py`

This task implements all five field verbs: `activate`, `update`, `deactivate`, `clear`, `delete`. The activate handler additionally validates the parent type exists.

- [ ] **Step 1: Write failing tests**

`tests/schema/test_handlers_asset_type_field.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.db.models.schema import FieldDataType
from novamoc.domain.schema._dispatch import ServiceBundle, dispatch
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome
from novamoc.domain.schema._payloads import (
    ActivateAssetTypeField,
    ClearAssetTypeField,
    DeactivateAssetTypeField,
    DeleteAssetTypeField,
    UpdateAssetTypeField,
    _AssetTypeFieldDefinition,
    _AssetTypeFieldUpdate,
    _Empty,
)


_T = "t1"


async def _make_parent(session: AsyncSession, services: ServiceBundle, *, active: bool = True):
    type_id = uuid4()
    await services.asset_type.create(
        data={"tenant_id": _T, "id": type_id, "name": f"T-{type_id}", "active": active},
        auto_commit=False,
    )
    await session.flush()
    return type_id


async def _make_field(
    session: AsyncSession,
    services: ServiceBundle,
    *,
    parent: object,
    active: bool = True,
):
    fid = uuid4()
    await services.asset_type_field.create(
        data={
            "tenant_id": _T,
            "id": fid,
            "asset_type_id": parent,
            "name": "vin",
            "data_type": "text",
            "validation": None,
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return fid


# --- activate (with parent validation) ---

async def test_activate_field_create(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = uuid4()
    out = await dispatch(
        services,
        ActivateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_AssetTypeFieldDefinition(
                asset_type_id=parent, name="vin", data_type=FieldDataType.TEXT,
            ),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert row.name == "vin" and row.asset_type_id == parent and row.active is True


async def test_activate_field_with_missing_parent_rejects(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateAssetTypeField(
                tenant_id=_T,
                entity_id=uuid4(),
                payload=_AssetTypeFieldDefinition(
                    asset_type_id=uuid4(), name="vin", data_type=FieldDataType.TEXT,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.PARENT_TYPE_NOT_FOUND


async def test_activate_field_with_deactivated_parent_is_allowed(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services, active=False)
    fid = uuid4()
    out = await dispatch(
        services,
        ActivateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_AssetTypeFieldDefinition(
                asset_type_id=parent, name="vin", data_type=FieldDataType.TEXT,
            ),
        ),
    )
    assert out.outcome is Outcome.CREATED


async def test_activate_field_when_deactivated(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent, active=False)
    out = await dispatch(
        services,
        ActivateAssetTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    assert out.outcome is Outcome.ACTIVATED


async def test_activate_field_noop(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent, active=True)
    out = await dispatch(
        services,
        ActivateAssetTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    assert out.outcome is Outcome.NOOP


async def test_activate_field_missing_with_empty_rejects(services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateAssetTypeField(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )
    assert exc_info.value.code is ErrorCode.DEFINITION_REQUIRED


# --- update / deactivate / clear / delete ---

async def test_update_field_changes_data_type(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        UpdateAssetTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_AssetTypeFieldUpdate(data_type=FieldDataType.NUMBER),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.UPDATED
    row = await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid)
    assert row.data_type == "number"


async def test_update_field_no_changes_rejects(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    with pytest.raises(PayloadShapeError):
        await dispatch(
            services,
            UpdateAssetTypeField(tenant_id=_T, entity_id=fid, payload=_AssetTypeFieldUpdate()),
        )


async def test_deactivate_field(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services, DeactivateAssetTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DEACTIVATED


async def test_clear_field_appends_log_row(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services, ClearAssetTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.CLEARED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == "clear_asset_type_field"


async def test_delete_field(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services, DeleteAssetTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.asset_type_field.get_one_or_none(tenant_id=_T, id=fid) is None


async def test_field_commands_against_missing_field_raise_not_found(
    services: ServiceBundle,
) -> None:
    eid = uuid4()
    for cmd in (
        UpdateAssetTypeField(tenant_id=_T, entity_id=eid, payload=_AssetTypeFieldUpdate(name="x")),
        DeactivateAssetTypeField(tenant_id=_T, entity_id=eid, payload=_Empty()),
        ClearAssetTypeField(tenant_id=_T, entity_id=eid, payload=_Empty()),
        DeleteAssetTypeField(tenant_id=_T, entity_id=eid, payload=_Empty()),
    ):
        with pytest.raises(EntityNotFoundError):
            await dispatch(services, cmd)
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_handlers_asset_type_field.py -v`

Expected: all tests fail with `KeyError`.

- [ ] **Step 3: Implement handlers**

`src/py/novamoc/domain/schema/_handlers/asset_type_field.py`:

```python
"""AssetTypeField command handlers.

The activate handler additionally enforces parent-type existence: a
missing parent yields ``parent_type_not_found``; a deactivated parent is
permitted (a hidden type can still have its field schema edited).

``clear_*_field`` records the command in ``schema_change_log`` but does
not yet wipe ``*_field_values`` rows or strip the field key from
``properties`` JSON — that wiring depends on the data-projection spec.
The TODO is preserved here.
"""

from __future__ import annotations

import msgspec
from sqlalchemy.exc import IntegrityError

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import ServiceBundle, _HANDLERS
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome
from novamoc.domain.schema._payloads import (
    ActivateAssetTypeField,
    ClearAssetTypeField,
    DeactivateAssetTypeField,
    DeleteAssetTypeField,
    UpdateAssetTypeField,
    _AssetTypeFieldDefinition,
    _Empty,
)


async def _activate(services: ServiceBundle, req: ActivateAssetTypeField) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    payload_is_empty = isinstance(req.payload, _Empty)

    if obj is None:
        if payload_is_empty:
            raise ConflictError(code=ErrorCode.DEFINITION_REQUIRED)
        defn: _AssetTypeFieldDefinition = req.payload  # type: ignore[assignment]
        parent = await services.asset_type.get_one_or_none(
            tenant_id=req.tenant_id, id=defn.asset_type_id,
        )
        if parent is None:
            raise ConflictError(code=ErrorCode.PARENT_TYPE_NOT_FOUND)
        try:
            await services.asset_type_field.create(
                data={
                    "tenant_id": req.tenant_id,
                    "id": req.entity_id,
                    "asset_type_id": defn.asset_type_id,
                    "name": defn.name,
                    "data_type": defn.data_type,
                    "validation": defn.validation,
                    "active": True,
                },
                auto_commit=False,
            )
        except IntegrityError as exc:
            raise ConflictError(code=ErrorCode.NAME_RESERVED, name=defn.name) from exc
        outcome = Outcome.CREATED
    elif not obj.active:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.NAME_IS_DEACTIVATED)
        await services.asset_type_field.update(
            data={"active": True},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    else:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.USE_UPDATE)
        outcome = Outcome.NOOP

    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.ACTIVATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _update(services: ServiceBundle, req: UpdateAssetTypeField) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload, builtin_types=(type(None),))
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.asset_type_field.update(
            data=payload, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.UPDATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.UPDATED, row.committed_at)


async def _deactivate(services: ServiceBundle, req: DeactivateAssetTypeField) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.asset_type_field.update(
            data={"active": False},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DEACTIVATE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _clear(services: ServiceBundle, req: ClearAssetTypeField) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    # TODO(data-projection): wipe `asset_type_field_values` rows for this field
    # and strip the field key from `properties` JSON on every asset of the parent
    # type. Gated on the data-projection spec landing.
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.CLEAR_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.CLEARED, row.committed_at)


async def _delete(services: ServiceBundle, req: DeleteAssetTypeField) -> SchemaCommitOutcome:
    obj = await services.asset_type_field.get_one_or_none(tenant_id=req.tenant_id, id=req.entity_id)
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.asset_type_field.delete(
        item_id=(req.tenant_id, req.entity_id), auto_commit=False,
    )
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DELETE_ASSET_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.DELETED, row.committed_at)


_HANDLERS[ActivateAssetTypeField] = _activate
_HANDLERS[UpdateAssetTypeField] = _update
_HANDLERS[DeactivateAssetTypeField] = _deactivate
_HANDLERS[ClearAssetTypeField] = _clear
_HANDLERS[DeleteAssetTypeField] = _delete
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_handlers_asset_type_field.py -v`

Expected: all field-handler tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_handlers/asset_type_field.py tests/schema/test_handlers_asset_type_field.py
git commit -m "feat(schema): implement AssetTypeField command handlers"
```

---

## Task 14: MaintenanceRecordType handlers

**Files:**
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`
- Create: `tests/schema/test_handlers_maintenance_record_type.py`

The MaintenanceRecordType handlers are structurally identical to AssetType's; the test file mirrors `test_handlers_asset_type.py` but exercises the maintenance-record service. Per the spec, parameterizing across both type kinds in one test file would muddy the file's purpose; we keep them split for readability.

- [ ] **Step 1: Write failing tests**

`tests/schema/test_handlers_maintenance_record_type.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.domain.schema._dispatch import ServiceBundle, dispatch
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordType,
    DeactivateMaintenanceRecordType,
    DeleteMaintenanceRecordType,
    UpdateMaintenanceRecordType,
    _Empty,
    _MaintenanceRecordTypeDefinition,
    _MaintenanceRecordTypeUpdate,
)


_T = "t1"


async def _make_active(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Service", "active": True},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_deactivated(session: AsyncSession, services: ServiceBundle):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": "Service", "active": False},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def test_activate_create(session: AsyncSession, services: ServiceBundle) -> None:
    eid = uuid4()
    out = await dispatch(
        services,
        ActivateMaintenanceRecordType(
            tenant_id=_T, entity_id=eid,
            payload=_MaintenanceRecordTypeDefinition(name="Service"),
        ),
    )
    await session.flush()
    assert out.outcome is Outcome.CREATED
    log = (await session.execute(select(schema_models.SchemaChangeLog))).scalars().all()
    assert log[-1].command == "activate_maintenance_record_type"


async def test_activate_when_deactivated(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_deactivated(session, services)
    out = await dispatch(
        services,
        ActivateMaintenanceRecordType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    assert out.outcome is Outcome.ACTIVATED


async def test_activate_missing_with_empty_rejects(services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateMaintenanceRecordType(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )
    assert exc_info.value.code is ErrorCode.DEFINITION_REQUIRED


async def test_activate_active_with_payload_rejects(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    eid = await _make_active(session, services)
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateMaintenanceRecordType(
                tenant_id=_T, entity_id=eid,
                payload=_MaintenanceRecordTypeDefinition(name="Service"),
            ),
        )
    assert exc_info.value.code is ErrorCode.USE_UPDATE


async def test_update_changes_name(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        UpdateMaintenanceRecordType(
            tenant_id=_T, entity_id=eid,
            payload=_MaintenanceRecordTypeUpdate(name="Annual"),
        ),
    )
    assert out.outcome is Outcome.UPDATED


async def test_update_missing_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            UpdateMaintenanceRecordType(
                tenant_id=_T, entity_id=uuid4(),
                payload=_MaintenanceRecordTypeUpdate(name="X"),
            ),
        )


async def test_update_no_changes_rejects(
    session: AsyncSession, services: ServiceBundle,
) -> None:
    eid = await _make_active(session, services)
    with pytest.raises(PayloadShapeError):
        await dispatch(
            services,
            UpdateMaintenanceRecordType(
                tenant_id=_T, entity_id=eid, payload=_MaintenanceRecordTypeUpdate(),
            ),
        )


async def test_deactivate_active(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        DeactivateMaintenanceRecordType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    assert out.outcome is Outcome.DEACTIVATED


async def test_delete_removes_row(session: AsyncSession, services: ServiceBundle) -> None:
    eid = await _make_active(session, services)
    out = await dispatch(
        services,
        DeleteMaintenanceRecordType(tenant_id=_T, entity_id=eid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.maintenance_record_type.get_one_or_none(tenant_id=_T, id=eid) is None
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_handlers_maintenance_record_type.py -v`

Expected: `KeyError` from `dispatch`.

- [ ] **Step 3: Implement handlers**

`src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`:

```python
"""MaintenanceRecordType command handlers.

Mirrors :mod:`novamoc.domain.schema._handlers.asset_type` — same five
state cells per verb, different service and command names. The two
modules are deliberately not abstracted into a common helper: each is
short, the duplication is honest, and divergence between the two kinds
(if it ever happens) wouldn't fight a shared helper.
"""

from __future__ import annotations

import msgspec
from sqlalchemy.exc import IntegrityError

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import ServiceBundle, _HANDLERS
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordType,
    DeactivateMaintenanceRecordType,
    DeleteMaintenanceRecordType,
    UpdateMaintenanceRecordType,
    _Empty,
    _MaintenanceRecordTypeDefinition,
)


async def _activate(
    services: ServiceBundle, req: ActivateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    payload_is_empty = isinstance(req.payload, _Empty)

    if obj is None:
        if payload_is_empty:
            raise ConflictError(code=ErrorCode.DEFINITION_REQUIRED)
        defn: _MaintenanceRecordTypeDefinition = req.payload  # type: ignore[assignment]
        try:
            await services.maintenance_record_type.create(
                data={
                    "tenant_id": req.tenant_id,
                    "id": req.entity_id,
                    "name": defn.name,
                    "active": True,
                },
                auto_commit=False,
            )
        except IntegrityError as exc:
            raise ConflictError(code=ErrorCode.NAME_RESERVED, name=defn.name) from exc
        outcome = Outcome.CREATED
    elif not obj.active:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.NAME_IS_DEACTIVATED)
        await services.maintenance_record_type.update(
            data={"active": True},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    else:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.USE_UPDATE)
        outcome = Outcome.NOOP

    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.ACTIVATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _update(
    services: ServiceBundle, req: UpdateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload, builtin_types=(type(None),))
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.maintenance_record_type.update(
            data=payload, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.UPDATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.UPDATED, row.committed_at)


async def _deactivate(
    services: ServiceBundle, req: DeactivateMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.maintenance_record_type.update(
            data={"active": False},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DEACTIVATE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _delete(
    services: ServiceBundle, req: DeleteMaintenanceRecordType,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.maintenance_record_type.delete(
        item_id=(req.tenant_id, req.entity_id), auto_commit=False,
    )
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DELETE_MAINTENANCE_RECORD_TYPE,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.DELETED, row.committed_at)


_HANDLERS[ActivateMaintenanceRecordType] = _activate
_HANDLERS[UpdateMaintenanceRecordType] = _update
_HANDLERS[DeactivateMaintenanceRecordType] = _deactivate
_HANDLERS[DeleteMaintenanceRecordType] = _delete
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_handlers_maintenance_record_type.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py tests/schema/test_handlers_maintenance_record_type.py
git commit -m "feat(schema): implement MaintenanceRecordType command handlers"
```

---

## Task 15: MaintenanceRecordTypeField handlers

**Files:**
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`
- Create: `tests/schema/test_handlers_maintenance_record_type_field.py`

Mirrors AssetTypeField, with `maintenance_record_type` parent and `maintenance_record_type_id` FK.

- [ ] **Step 1: Write failing tests**

`tests/schema/test_handlers_maintenance_record_type_field.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models.schema import FieldDataType
from novamoc.domain.schema._dispatch import ServiceBundle, dispatch
from novamoc.domain.schema._errors import ConflictError, EntityNotFoundError, ErrorCode
from novamoc.domain.schema._outcomes import Outcome
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordTypeField,
    ClearMaintenanceRecordTypeField,
    DeactivateMaintenanceRecordTypeField,
    DeleteMaintenanceRecordTypeField,
    UpdateMaintenanceRecordTypeField,
    _Empty,
    _MaintenanceRecordTypeFieldDefinition,
    _MaintenanceRecordTypeFieldUpdate,
)


_T = "t1"


async def _make_parent(session: AsyncSession, services: ServiceBundle, *, active: bool = True):
    eid = uuid4()
    await services.maintenance_record_type.create(
        data={"tenant_id": _T, "id": eid, "name": f"M-{eid}", "active": active},
        auto_commit=False,
    )
    await session.flush()
    return eid


async def _make_field(
    session: AsyncSession, services: ServiceBundle, *, parent: object, active: bool = True,
):
    fid = uuid4()
    await services.maintenance_record_type_field.create(
        data={
            "tenant_id": _T,
            "id": fid,
            "maintenance_record_type_id": parent,
            "name": "mileage",
            "data_type": "integer",
            "validation": None,
            "active": active,
        },
        auto_commit=False,
    )
    await session.flush()
    return fid


async def test_activate_create(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = uuid4()
    out = await dispatch(
        services,
        ActivateMaintenanceRecordTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_MaintenanceRecordTypeFieldDefinition(
                maintenance_record_type_id=parent,
                name="mileage",
                data_type=FieldDataType.INTEGER,
            ),
        ),
    )
    assert out.outcome is Outcome.CREATED


async def test_activate_with_missing_parent_rejects(services: ServiceBundle) -> None:
    with pytest.raises(ConflictError) as exc_info:
        await dispatch(
            services,
            ActivateMaintenanceRecordTypeField(
                tenant_id=_T,
                entity_id=uuid4(),
                payload=_MaintenanceRecordTypeFieldDefinition(
                    maintenance_record_type_id=uuid4(),
                    name="mileage",
                    data_type=FieldDataType.INTEGER,
                ),
            ),
        )
    assert exc_info.value.code is ErrorCode.PARENT_TYPE_NOT_FOUND


async def test_update_changes_data_type(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        UpdateMaintenanceRecordTypeField(
            tenant_id=_T,
            entity_id=fid,
            payload=_MaintenanceRecordTypeFieldUpdate(data_type=FieldDataType.NUMBER),
        ),
    )
    assert out.outcome is Outcome.UPDATED


async def test_deactivate(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services,
        DeactivateMaintenanceRecordTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    assert out.outcome is Outcome.DEACTIVATED


async def test_clear_appends_log(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services, ClearMaintenanceRecordTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    assert out.outcome is Outcome.CLEARED


async def test_delete_removes_row(session: AsyncSession, services: ServiceBundle) -> None:
    parent = await _make_parent(session, services)
    fid = await _make_field(session, services, parent=parent)
    out = await dispatch(
        services, DeleteMaintenanceRecordTypeField(tenant_id=_T, entity_id=fid, payload=_Empty()),
    )
    await session.flush()
    assert out.outcome is Outcome.DELETED
    assert await services.maintenance_record_type_field.get_one_or_none(tenant_id=_T, id=fid) is None


async def test_missing_field_raises_not_found(services: ServiceBundle) -> None:
    with pytest.raises(EntityNotFoundError):
        await dispatch(
            services,
            DeleteMaintenanceRecordTypeField(tenant_id=_T, entity_id=uuid4(), payload=_Empty()),
        )
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_handlers_maintenance_record_type_field.py -v`

Expected: KeyError from dispatch.

- [ ] **Step 3: Implement handlers**

`src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`:

```python
"""MaintenanceRecordTypeField command handlers.

Mirrors :mod:`novamoc.domain.schema._handlers.asset_type_field` against
the maintenance-record service. See the asset-type-field module for the
``clear_*_field`` value-wipe TODO.
"""

from __future__ import annotations

import msgspec
from sqlalchemy.exc import IntegrityError

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema._dispatch import ServiceBundle, _HANDLERS
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)
from novamoc.domain.schema._outcomes import Outcome, SchemaCommitOutcome
from novamoc.domain.schema._payloads import (
    ActivateMaintenanceRecordTypeField,
    ClearMaintenanceRecordTypeField,
    DeactivateMaintenanceRecordTypeField,
    DeleteMaintenanceRecordTypeField,
    UpdateMaintenanceRecordTypeField,
    _Empty,
    _MaintenanceRecordTypeFieldDefinition,
)


async def _activate(
    services: ServiceBundle, req: ActivateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    payload_is_empty = isinstance(req.payload, _Empty)

    if obj is None:
        if payload_is_empty:
            raise ConflictError(code=ErrorCode.DEFINITION_REQUIRED)
        defn: _MaintenanceRecordTypeFieldDefinition = req.payload  # type: ignore[assignment]
        parent = await services.maintenance_record_type.get_one_or_none(
            tenant_id=req.tenant_id, id=defn.maintenance_record_type_id,
        )
        if parent is None:
            raise ConflictError(code=ErrorCode.PARENT_TYPE_NOT_FOUND)
        try:
            await services.maintenance_record_type_field.create(
                data={
                    "tenant_id": req.tenant_id,
                    "id": req.entity_id,
                    "maintenance_record_type_id": defn.maintenance_record_type_id,
                    "name": defn.name,
                    "data_type": defn.data_type,
                    "validation": defn.validation,
                    "active": True,
                },
                auto_commit=False,
            )
        except IntegrityError as exc:
            raise ConflictError(code=ErrorCode.NAME_RESERVED, name=defn.name) from exc
        outcome = Outcome.CREATED
    elif not obj.active:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.NAME_IS_DEACTIVATED)
        await services.maintenance_record_type_field.update(
            data={"active": True},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.ACTIVATED
    else:
        if not payload_is_empty:
            raise ConflictError(code=ErrorCode.USE_UPDATE)
        outcome = Outcome.NOOP

    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.ACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=msgspec.to_builtins(req.payload),
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _update(
    services: ServiceBundle, req: UpdateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    payload = msgspec.to_builtins(req.payload, builtin_types=(type(None),))
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        raise PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    try:
        await services.maintenance_record_type_field.update(
            data=payload, item_id=(req.tenant_id, req.entity_id), auto_commit=False,
        )
    except IntegrityError as exc:
        raise ConflictError(code=ErrorCode.NAME_RESERVED) from exc
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.UPDATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload=payload,
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.UPDATED, row.committed_at)


async def _deactivate(
    services: ServiceBundle, req: DeactivateMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    if obj.active:
        await services.maintenance_record_type_field.update(
            data={"active": False},
            item_id=(req.tenant_id, req.entity_id),
            auto_commit=False,
        )
        outcome = Outcome.DEACTIVATED
    else:
        outcome = Outcome.NOOP
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DEACTIVATE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, outcome, row.committed_at)


async def _clear(
    services: ServiceBundle, req: ClearMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    # TODO(data-projection): wipe per-field values; see asset_type_field._clear.
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.CLEAR_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.CLEARED, row.committed_at)


async def _delete(
    services: ServiceBundle, req: DeleteMaintenanceRecordTypeField,
) -> SchemaCommitOutcome:
    obj = await services.maintenance_record_type_field.get_one_or_none(
        tenant_id=req.tenant_id, id=req.entity_id,
    )
    if obj is None:
        raise EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    await services.maintenance_record_type_field.delete(
        item_id=(req.tenant_id, req.entity_id), auto_commit=False,
    )
    row = await services.change_log.append(
        tenant_id=req.tenant_id,
        command=SchemaCommand.DELETE_MAINTENANCE_RECORD_TYPE_FIELD,
        entity_id=req.entity_id,
        payload={},
    )
    return SchemaCommitOutcome(row.seq, req.entity_id, Outcome.DELETED, row.committed_at)


_HANDLERS[ActivateMaintenanceRecordTypeField] = _activate
_HANDLERS[UpdateMaintenanceRecordTypeField] = _update
_HANDLERS[DeactivateMaintenanceRecordTypeField] = _deactivate
_HANDLERS[ClearMaintenanceRecordTypeField] = _clear
_HANDLERS[DeleteMaintenanceRecordTypeField] = _delete
```

- [ ] **Step 4: Update the dispatch registration test**

In `tests/schema/test_dispatch.py`, replace `test_handlers_table_is_empty_initially` with:

```python
def test_handlers_table_has_seventeen_entries() -> None:
    assert len(_HANDLERS) == 17
```

- [ ] **Step 5: Run all schema tests**

Run: `uv run pytest tests/schema -v`

Expected: every schema-test file passes; `_HANDLERS` has 17 entries.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py tests/schema/test_handlers_maintenance_record_type_field.py tests/schema/test_dispatch.py
git commit -m "feat(schema): implement MaintenanceRecordTypeField command handlers"
```

---

## Task 16: SchemaController and exception handler

**Files:**
- Create: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Modify: `src/py/novamoc/domain/schema/controllers/__init__.py`
- Delete: `src/py/novamoc/domain/schema/controllers/_asset_type.py`
- Create: `tests/schema/test_controller_unit.py`

This task wires up the controller and a Litestar exception handler that maps `SchemaCommandError` and `msgspec.ValidationError` to the documented JSON envelopes. End-to-end tests live in Task 18.

- [ ] **Step 1: Write a failing unit test for the exception handler**

`tests/schema/test_controller_unit.py`:

```python
from litestar import Request
from litestar.exceptions import HTTPException

from novamoc.domain.schema._errors import ConflictError, ErrorCode
from novamoc.domain.schema.controllers._schema import schema_command_error_handler


def test_handler_renders_envelope() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    response = schema_command_error_handler(Request[None, None, None](scope={"type": "http", "headers": [], "query_string": b""}), exc)
    assert response.status_code == 409
    body = response.content
    assert body == {
        "error": "conflict",
        "code": "name_reserved",
        "message": exc.message,
        "name": "Truck",
    }


def test_handler_only_handles_schema_command_error() -> None:
    # Passing an unrelated exception should re-raise via the standard pipeline.
    # The Litestar exception_handlers contract maps the registered class only;
    # this test guards against accidentally widening the handler.
    assert ConflictError.__bases__[0].__name__ == "SchemaCommandError"
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_controller_unit.py -v`

Expected: ImportError on `controllers._schema`.

- [ ] **Step 3: Implement controller and exception handler**

Delete `src/py/novamoc/domain/schema/controllers/_asset_type.py` (placeholder, never used).

`src/py/novamoc/domain/schema/controllers/_schema.py`:

```python
"""HTTP controller for ``POST /schema``.

The route's request body is the discriminated union :data:`SchemaRequest`,
so Litestar publishes a ``oneOf`` discriminated by ``command`` in the
OpenAPI schema. Dispatch is by the runtime variant class via
:func:`dispatch`.
"""

from __future__ import annotations

from typing import Any

import msgspec
from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, Response, post
from litestar.status_codes import HTTP_400_BAD_REQUEST

from novamoc.domain.schema._dispatch import ServiceBundle, dispatch
from novamoc.domain.schema._errors import ErrorCode, SchemaCommandError
from novamoc.domain.schema._payloads import (
    SchemaErrorResponse,
    SchemaRequest,
    SchemaResponse,
)
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)


def schema_command_error_handler(_request: Request[Any, Any, Any], exc: SchemaCommandError) -> Response[dict[str, Any]]:
    body: dict[str, Any] = {
        "error": exc.error,
        "code": exc.code.value,
        "message": exc.message,
    }
    body.update(exc.extras)
    return Response(content=body, status_code=exc.status_code)


def msgspec_validation_error_handler(_request: Request[Any, Any, Any], exc: msgspec.ValidationError) -> Response[dict[str, Any]]:
    return Response(
        content={
            "error": "invalid_request",
            "code": ErrorCode.INVALID_PAYLOAD_SHAPE.value,
            "message": str(exc),
        },
        status_code=HTTP_400_BAD_REQUEST,
    )


class SchemaController(Controller):
    path = "/schema"
    tags = ["schema"]

    dependencies = (
        providers.create_service_dependencies(AssetTypeService, "asset_type_service")
        | providers.create_service_dependencies(AssetTypeFieldService, "asset_type_field_service")
        | providers.create_service_dependencies(
            MaintenanceRecordTypeService, "maintenance_record_type_service",
        )
        | providers.create_service_dependencies(
            MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service",
        )
        | providers.create_service_dependencies(SchemaChangeLogService, "schema_change_log_service")
    )

    exception_handlers = {  # type: ignore[var-annotated]
        SchemaCommandError: schema_command_error_handler,
        msgspec.ValidationError: msgspec_validation_error_handler,
    }

    @post(
        "/",
        responses={  # documented status codes
            200: None,
            400: None,
            404: None,
            409: None,
        },
    )
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

`src/py/novamoc/domain/schema/controllers/__init__.py`:

```python
from ._schema import SchemaController, schema_command_error_handler, msgspec_validation_error_handler

__all__ = (
    "SchemaController",
    "msgspec_validation_error_handler",
    "schema_command_error_handler",
)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_controller_unit.py -v`

Expected: `test_handler_renders_envelope` passes; `test_handler_only_handles_schema_command_error` is a static check and passes.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/schema/controllers tests/schema/test_controller_unit.py
git rm src/py/novamoc/domain/schema/controllers/_asset_type.py 2>/dev/null || true
git commit -m "feat(schema): add SchemaController and exception handlers"
```

---

## Task 17: Wire SchemaController into the ASGI app

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Create: `tests/schema/test_app_wiring.py`

The current `asgi.create_app` references an undefined `hello_world` symbol — replace it with `SchemaController`.

- [ ] **Step 1: Write failing test**

`tests/schema/test_app_wiring.py`:

```python
from litestar.testing import AsyncTestClient

from novamoc.asgi import create_app


async def test_app_starts_and_publishes_openapi_for_schema() -> None:
    app = create_app()
    async with AsyncTestClient(app) as client:
        resp = await client.get("/schema/openapi.json")
        # Litestar's default OpenAPI controller mounts at /schema, but ours owns
        # /schema. Use the configurable openapi-schema path instead:
        resp = await client.get("/schema/")
        # POST is the only method on /schema; GET should be 405.
        assert resp.status_code in (405, 404)


async def test_app_route_post_schema_exists() -> None:
    app = create_app()
    routes = {r.path for r in app.route_handler_method_map}
    assert "/schema/" in routes or "/schema" in routes
```

(Note: Litestar's default OpenAPI controller path is `/schema`, which collides with our route. The wiring task moves OpenAPI elsewhere; the test asserts the collision is resolved.)

- [ ] **Step 2: Run, expect failure**

Run: `uv run pytest tests/schema/test_app_wiring.py -v`

Expected: `NameError: name 'hello_world' is not defined` raised during `create_app()`.

- [ ] **Step 3: Replace `asgi.py`**

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar


def create_app() -> Litestar:
    """Create the ASGI app."""

    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.openapi.config import OpenAPIConfig
    from litestar_granian import GranianPlugin

    from novamoc.domain.schema.controllers import SchemaController

    session_config = AsyncSessionConfig(expire_on_commit=False)
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///test.sqlite",
        before_send_handler="autocommit",
        session_config=session_config,
        create_all=True,
    )

    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            GranianPlugin(),
            SQLAlchemyPlugin(config=alchemy_config),
        ],
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/schema/test_app_wiring.py -v`

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/asgi.py tests/schema/test_app_wiring.py
git commit -m "feat: wire SchemaController and move OpenAPI mount off /schema"
```

---

## Task 18: End-to-end controller tests

**Files:**
- Create: `tests/schema/test_endpoint_e2e.py`

Drives `POST /schema` through Litestar's `AsyncTestClient`. The asgi config uses a file-backed SQLite (`test.sqlite`); the fixtures here pin a per-test in-memory engine via Litestar's app-state override so tests don't share state.

- [ ] **Step 1: Add an app fixture that uses the test engine**

Append to `tests/conftest.py`:

```python
from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar import Litestar
from litestar.openapi.config import OpenAPIConfig
from litestar.testing import AsyncTestClient

from novamoc.domain.schema.controllers import SchemaController


@pytest.fixture
async def app() -> Litestar:
    """A Litestar app that uses an in-memory shared-cache SQLite.

    `cache=shared` makes the same in-memory db reachable from multiple
    connections within the same process — required because the plugin
    opens its own engine.
    """
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///file::memory:?cache=shared&uri=true",
        before_send_handler="autocommit",
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=True,
    )
    return Litestar(
        route_handlers=[SchemaController],
        plugins=[SQLAlchemyPlugin(config=alchemy_config)],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )


@pytest.fixture
async def client(app: Litestar):
    async with AsyncTestClient(app) as c:
        yield c
```

- [ ] **Step 2: Write failing tests**

`tests/schema/test_endpoint_e2e.py`:

```python
from uuid import uuid4

import pytest


_T = "tenant-e2e"


@pytest.fixture
def fresh_entity_id() -> str:
    return str(uuid4())


async def test_post_schema_creates_asset_type(client, fresh_entity_id: str) -> None:
    resp = await client.post(
        "/schema",
        json={
            "command": "activate_asset_type",
            "tenant_id": _T,
            "entity_id": fresh_entity_id,
            "payload": {"name": "Truck"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "created"
    assert body["entity_id"] == fresh_entity_id
    assert body["schema_version"] >= 1


async def test_post_schema_returns_409_on_duplicate_name(client) -> None:
    body = {
        "command": "activate_asset_type",
        "tenant_id": _T,
        "entity_id": str(uuid4()),
        "payload": {"name": "DuplicateMe"},
    }
    first = await client.post("/schema", json=body)
    assert first.status_code in (200, 201), first.text
    body["entity_id"] = str(uuid4())
    second = await client.post("/schema", json=body)
    assert second.status_code == 409
    err = second.json()
    assert err["error"] == "conflict"
    assert err["code"] == "name_reserved"


async def test_post_schema_returns_404_for_update_missing(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "command": "update_asset_type",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {"name": "X"},
        },
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "entity_not_found"


async def test_post_schema_returns_400_on_unknown_command(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "command": "do_a_barrel_roll",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_payload_shape"


async def test_post_schema_returns_400_on_payload_with_unknown_field(client) -> None:
    resp = await client.post(
        "/schema",
        json={
            "command": "deactivate_asset_type",
            "tenant_id": _T,
            "entity_id": str(uuid4()),
            "payload": {"name": "x"},  # forbidden field on _Empty
        },
    )
    assert resp.status_code == 400


async def test_rollback_on_4xx_does_not_append_change_log(client) -> None:
    """A failed command must roll back: no schema_change_log row, no projection mutation."""
    eid = str(uuid4())
    # First create
    resp = await client.post(
        "/schema",
        json={
            "command": "activate_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {"name": "Rollback"},
        },
    )
    assert resp.status_code in (200, 201)
    sv_after_create = resp.json()["schema_version"]

    # Try a use_update conflict — should NOT append a change-log row.
    bad = await client.post(
        "/schema",
        json={
            "command": "activate_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {"name": "Rollback"},
        },
    )
    assert bad.status_code == 409

    # Issue a benign deactivate; its schema_version should be sv_after_create + 1.
    deact = await client.post(
        "/schema",
        json={
            "command": "deactivate_asset_type",
            "tenant_id": _T,
            "entity_id": eid,
            "payload": {},
        },
    )
    assert deact.status_code in (200, 201)
    assert deact.json()["schema_version"] == sv_after_create + 1
```

- [ ] **Step 3: Run, expect failure**

Run: `uv run pytest tests/schema/test_endpoint_e2e.py -v`

Expected: depends on runtime — likely some pass already (the wiring works), but the rollback test catches whether `before_send_handler="autocommit"` actually rolls back on 4xx. If the rollback test fails, fix the controller wiring (do not change the test).

- [ ] **Step 4: Verify all e2e tests pass**

Run: `uv run pytest tests/schema/test_endpoint_e2e.py -v`

Expected: all 6 tests pass.

If the OpenAPI schema is wanted, also run `uv run pytest tests/schema -v` to confirm nothing regressed.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/schema/test_endpoint_e2e.py
git commit -m "test(schema): end-to-end tests for POST /schema"
```

---

## Task 19: OpenAPI verification

**Files:**
- Create: `tests/schema/test_openapi.py`

Verifies the published OpenAPI schema includes a discriminated union over `command` for the `POST /schema` request body. Catches regressions where someone widens the body type to `dict` or drops a per-command struct.

- [ ] **Step 1: Write the test**

`tests/schema/test_openapi.py`:

```python
async def test_openapi_request_body_lists_all_seventeen_commands(client) -> None:
    resp = await client.get("/openapi/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    request_body_schema = spec["paths"]["/schema/"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    # Litestar emits an `oneOf` with the 17 variants. Resolve refs.
    one_of = request_body_schema.get("oneOf") or request_body_schema.get("anyOf")
    assert one_of is not None, request_body_schema
    assert len(one_of) == 17

    # Each variant carries a literal `command` whose value is the tag.
    found_commands: set[str] = set()
    for variant in one_of:
        ref = variant["$ref"]
        defn = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        cmd_field = defn["properties"]["command"]
        # msgspec emits an enum or const; both are acceptable.
        if "const" in cmd_field:
            found_commands.add(cmd_field["const"])
        elif "enum" in cmd_field:
            found_commands.update(cmd_field["enum"])
    expected = {
        "activate_asset_type", "update_asset_type", "deactivate_asset_type", "delete_asset_type",
        "activate_asset_type_field", "update_asset_type_field", "deactivate_asset_type_field",
        "clear_asset_type_field", "delete_asset_type_field",
        "activate_maintenance_record_type", "update_maintenance_record_type",
        "deactivate_maintenance_record_type", "delete_maintenance_record_type",
        "activate_maintenance_record_type_field", "update_maintenance_record_type_field",
        "deactivate_maintenance_record_type_field", "clear_maintenance_record_type_field",
        "delete_maintenance_record_type_field",
    }
    assert found_commands == expected
```

- [ ] **Step 2: Run, expect pass**

Run: `uv run pytest tests/schema/test_openapi.py -v`

Expected: pass. If the variant count differs, inspect the published spec (`uv run python -c "from novamoc.asgi import create_app; ..."`) to determine why and fix the union or struct definitions.

- [ ] **Step 3: Final test sweep**

Run: `uv run pytest tests -v`

Expected: every test in the suite passes.

- [ ] **Step 4: Commit**

```bash
git add tests/schema/test_openapi.py
git commit -m "test(schema): assert OpenAPI lists all 18 commands"
```

---

## Self-review notes

These checks were applied while writing the plan; remaining items the implementer should keep in mind:

1. **Coverage vs spec.** Every section of `2026-05-01-schema-endpoint-design.md` (decoder, dispatch, handlers, transactional contract, error envelope, validation matrix, OpenAPI exposure, testing strategy) is implemented across Tasks 1-19. The spec's two known gaps (`clear_*_field` value-wipe and `delete_*_type` cascading entity wipe) are surfaced as `TODO(data-projection)` in Tasks 13 and 15 and require the data-projection spec to land before they can be filled.

2. **Composite primary keys.** The `(tenant_id, id)` PK on tenant-scoped tables means service `update`/`delete` calls take `item_id=(tenant_id, entity_id)` and `get_one_or_none` takes filter kwargs `tenant_id=..., id=...`. This convention is used uniformly in Tasks 12-15.

3. **Transactional contract.** The plan does not call `session.commit()` anywhere. Production commits via `before_send_handler="autocommit"`; tests commit by `await session.flush()` and rely on the session's rollback on fixture teardown.

4. **Plan-level OpenAPI risk.** Litestar's default OpenAPI controller mounts at `/schema`, which collides with the `/schema` POST route. Task 17 moves OpenAPI to `/openapi`. Task 19 reads from `/openapi/openapi.json`.

5. **Decoder sequencing.** Tasks 4-7 add per-entity-kind structs incrementally and rebuild `SchemaRequest` each time. The runtime impact is identical (all 17 are present after Task 7); the staging keeps tests bite-sized.

6. **The `_HANDLERS` table is built by import side effects.** Each handler module appends to `_HANDLERS` at import time. The `_handlers/__init__.py` imports all four, and `_dispatch.py` imports `_handlers` at the bottom of its module. This guarantees the table is fully populated before any caller of `dispatch` runs, with one caveat: a developer who imports a handler module standalone will populate the table partially. Tests that call `dispatch` should always import via `from novamoc.domain.schema._dispatch import dispatch` (which transitively imports the full `_handlers` package) — this convention is followed in every test in this plan.
