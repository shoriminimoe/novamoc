# GET /sync/initial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the M2.3 bulk projection transfer endpoint (`GET /sync/initial`) — paginated streaming of the active tenant's `assets`, `maintenance_records`, `asset_field_values`, `maintenance_record_field_values` plus the `event_log.seq` cursor for incremental sync. Closes issue #33 and flips ADR-015 from Proposed to Accepted.

**Architecture:** A new `domain/sync/` package adds (a) an opaque base64-JSON cursor carrying `(start_seq, table, last_id)`, (b) an `InitialSyncPaginator` that walks the four projection tables in fixed order skipping empty intermediates, (c) a discriminated `InitialSyncBatch` response, and (d) a thin `SyncController`. `start_seq` is captured at first request and threaded through cursors so events arriving mid-transfer are not silently dropped. Tenant scoping is structural via the existing `db._listeners` Layer 1.

**Tech Stack:** Python 3.14, Litestar, advanced-alchemy + SQLAlchemy 2.x, aiosqlite, msgspec, pytest (asyncio auto mode), uv / ruff / ty.

**Spec:** [`docs/superpowers/specs/2026-05-18-sync-initial-design.md`](../specs/2026-05-18-sync-initial-design.md)

---

## File map

**New files:**
- `src/py/novamoc/domain/sync/__init__.py`
- `src/py/novamoc/domain/sync/_cursor.py`
- `src/py/novamoc/domain/sync/_payloads.py`
- `src/py/novamoc/domain/sync/services.py`
- `src/py/novamoc/domain/sync/_pagination.py`
- `src/py/novamoc/domain/sync/controllers/__init__.py`
- `src/py/novamoc/domain/sync/controllers/_sync.py`
- `tests/sync/__init__.py`
- `tests/sync/test_cursor.py`
- `tests/sync/test_pagination.py`
- `tests/sync/test_endpoint_sync_initial.py`
- `tests/sync/test_sync_cross_tenant_isolation.py`

**Modified files:**
- `src/py/novamoc/config.py` — add `INITIAL_SYNC_DEFAULT_BATCH_SIZE`, `INITIAL_SYNC_MAX_BATCH_SIZE`.
- `src/py/novamoc/domain/events/services.py` — add `EventLogService.current_seq()`.
- `src/py/novamoc/asgi.py` — register `SyncController` in `route_handlers`.
- `CLAUDE.md` — add "Initial sync endpoint (`GET /sync/initial`)" section.
- `docs/adr/015-initial-sync-full-dataset.md` — flip Status to Accepted.

---

## Task 1: Settings constants

**Files:**
- Modify: `src/py/novamoc/config.py:105-106` (after the `EVENT_CATCHUP_*` constants)

- [ ] **Step 1: Add the constants**

Edit `src/py/novamoc/config.py`, adding right after `EVENT_CATCHUP_MAX_BATCH_SIZE = 5000`:

```python
INITIAL_SYNC_DEFAULT_BATCH_SIZE = 1000
INITIAL_SYNC_MAX_BATCH_SIZE = 5000
```

- [ ] **Step 2: Sanity-check the module still imports**

Run: `uv run python -c "from novamoc.config import INITIAL_SYNC_DEFAULT_BATCH_SIZE, INITIAL_SYNC_MAX_BATCH_SIZE; print(INITIAL_SYNC_DEFAULT_BATCH_SIZE, INITIAL_SYNC_MAX_BATCH_SIZE)"`
Expected: `1000 5000`

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/config.py
git commit -m "$(cat <<'EOF'
feat(config): initial-sync batch-size constants (M2.3)

Module-level constants for GET /sync/initial. Defaults and max chosen
to match the events catch-up endpoint's max for operational consistency
while landing in ADR-015's "few thousand per batch" guidance.
EOF
)"
```

---

## Task 2: `EventLogService.current_seq()`

We need `MAX(event_log.seq) WHERE tenant_id = <ctx>` (with 0 on empty). Adding it to `EventLogService` mirrors `SchemaChangeLogService.current_version()` and routes through Layer 1's aggregate-fallback path for tenant scoping.

**Files:**
- Modify: `src/py/novamoc/domain/events/services.py`
- Test: implicit — exercised by paginator tests in Task 7+; no standalone test.

- [ ] **Step 1: Add the method**

Replace the entire content of `src/py/novamoc/domain/events/services.py` with:

```python
"""Service wrappers for the events domain.

:class:`EventLogService` provides an advanced-alchemy repository over the
append-only ``event_log`` table (ADR-011). Same pattern as the schema
services; tenant scoping is supplied by the listener layer.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service
from sqlalchemy import func, select

from novamoc.db.models.data import EventLog


class EventLogService(service.SQLAlchemyAsyncRepositoryService[EventLog]):
    class Repo(repository.SQLAlchemyAsyncRepository[EventLog]):
        model_type = EventLog

    repository_type = Repo

    async def current_seq(self) -> int:
        """Return the tenant's current ``MAX(event_log.seq)`` (or 0).

        Tenant scope is supplied by Layer 1's aggregate-fallback path
        (``db._listeners._inject_tenant_filter``): this scalar aggregate
        has an empty ``state.all_mappers``, so ``with_loader_criteria``
        has nothing to attach to. The fallback walks the FROM clause,
        finds ``event_log``, and stamps ``WHERE tenant_id = <ctx>``
        directly on the Core ``Select``. Mirror of
        :meth:`SchemaChangeLogService.current_version`.
        """
        stmt = select(func.coalesce(func.max(EventLog.seq), 0))
        result = await self.repository.session.execute(stmt)
        return int(result.scalar_one())


__all__ = ("EventLogService",)
```

- [ ] **Step 2: Ensure existing events tests still pass**

Run: `uv run pytest tests/events -q`
Expected: PASS (all existing tests; no behavior change).

- [ ] **Step 3: Commit**

```bash
git add src/py/novamoc/domain/events/services.py
git commit -m "$(cat <<'EOF'
feat(events): EventLogService.current_seq() (M2.3)

Mirror of SchemaChangeLogService.current_version() but for event_log.
M2.3's initial-sync paginator needs the per-tenant MAX(seq) to capture
start_seq at the beginning of a multi-request transfer.
EOF
)"
```

---

## Task 3: Cursor module (TDD — pure functions)

**Files:**
- Create: `src/py/novamoc/domain/sync/__init__.py`
- Create: `src/py/novamoc/domain/sync/_cursor.py`
- Create: `tests/sync/__init__.py`
- Create: `tests/sync/test_cursor.py`

- [ ] **Step 1: Create empty `__init__.py` files**

Create `src/py/novamoc/domain/sync/__init__.py` with content:

```python
"""Initial-sync (M2.3) domain — bulk projection transfer (ADR-015)."""
```

Create `tests/sync/__init__.py` empty (zero bytes is fine).

- [ ] **Step 2: Write the failing cursor test file**

Create `tests/sync/test_cursor.py`:

```python
"""Unit tests for the opaque sync cursor."""

from __future__ import annotations

import pytest

from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.sync._cursor import (
    CursorState,
    InitialSyncTable,
    decode_cursor,
    encode_cursor,
)


@pytest.mark.parametrize(
    "table,last_id",
    [
        (InitialSyncTable.ASSETS, None),
        (InitialSyncTable.ASSETS, "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f"),
        (InitialSyncTable.ASSET_FIELD_VALUES, None),
        (
            InitialSyncTable.ASSET_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:col:name",
        ),
        (InitialSyncTable.MAINTENANCE_RECORDS, None),
        (
            InitialSyncTable.MAINTENANCE_RECORD_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:f0a1b2c3-d4e5-6789-abcd-ef0123456789",
        ),
    ],
)
def test_cursor_roundtrip(table: InitialSyncTable, last_id: str | None) -> None:
    state = CursorState(start_seq=17, table=table, last_id=last_id)
    encoded = encode_cursor(state)
    assert isinstance(encoded, str)
    decoded = decode_cursor(encoded)
    assert decoded == state


def test_cursor_decode_rejects_garbage() -> None:
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor("not-base64!@#")
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_non_json_base64() -> None:
    # Valid base64 but the bytes are not JSON.
    import base64

    token = base64.urlsafe_b64encode(b"\x00\x01\x02").rstrip(b"=").decode()
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_missing_fields() -> None:
    import base64
    import json

    token = base64.urlsafe_b64encode(json.dumps({"start_seq": 1}).encode()).rstrip(
        b"="
    ).decode()
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_unknown_table() -> None:
    import base64
    import json

    token = base64.urlsafe_b64encode(
        json.dumps(
            {"start_seq": 1, "table": "users", "last_id": None}
        ).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_accepts_padded_token() -> None:
    """Be liberal in what we accept: padded base64 from naive clients."""
    state = CursorState(
        start_seq=42, table=InitialSyncTable.ASSETS, last_id=None
    )
    encoded = encode_cursor(state)
    # Force-add padding back so the decoder must handle the canonical
    # padded form too.
    padded = encoded + "=" * (-len(encoded) % 4)
    assert decode_cursor(padded) == state
```

- [ ] **Step 3: Run tests to verify they fail (no module yet)**

Run: `uv run pytest tests/sync/test_cursor.py -v`
Expected: FAIL with `ImportError: cannot import name 'CursorState' from 'novamoc.domain.sync._cursor'`.

- [ ] **Step 4: Write the cursor module**

Create `src/py/novamoc/domain/sync/_cursor.py`:

```python
"""Opaque cursor for the initial-sync transfer.

Encodes ``(start_seq, table, last_id)`` as URL-safe base64 of compact JSON.
The cursor is *not* signed: see the design spec §"Cursor encoding" for
the threat model — a client that tampers only hurts itself, and Layer 1
of the tenant-scoping listeners scopes every read regardless.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novamoc.domain._errors import ErrorCode, PayloadShapeError


class InitialSyncTable(StrEnum):
    """The four projection tables an initial sync walks, in order.

    The string values double as the discriminator tags on the response
    body union (see ``_payloads._SyncBody``).
    """

    ASSETS = "assets"
    ASSET_FIELD_VALUES = "asset_field_values"
    MAINTENANCE_RECORDS = "maintenance_records"
    MAINTENANCE_RECORD_FIELD_VALUES = "maintenance_record_field_values"


@dataclass(frozen=True, slots=True)
class CursorState:
    """State threaded across one client's initial-sync requests.

    Attributes:
        start_seq: ``MAX(event_log.seq)`` observed on the first
            request; emitted as ``event_log_cursor`` on the terminal
            batch. Threaded so that mid-transfer event arrivals don't
            shift the cursor (design spec §"Why ``start_seq`` on the
            first request").
        table: Next projection table to read from.
        last_id: Last-seen primary key in ``table``, or ``None`` to
            start at the beginning. Entity tables: the UUID as a string.
            Field-value tables: ``"<entity_uuid>:<field_id>"`` (split on
            the first colon, so a ``col:name`` field id parses cleanly).
    """

    start_seq: int
    table: InitialSyncTable
    last_id: str | None


def encode_cursor(state: CursorState) -> str:
    """URL-safe base64 of compact JSON. Trailing ``=`` padding stripped."""
    payload = {
        "start_seq": state.start_seq,
        "table": state.table.value,
        "last_id": state.last_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> CursorState:
    """Inverse of :func:`encode_cursor`.

    Raises:
        PayloadShapeError: token isn't valid base64-JSON, the decoded
            object is missing required fields, has the wrong field
            types, or names an unknown ``table``.
    """
    # Liberal in what we accept: re-add ``=`` padding lost in transit.
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor is not valid base64",
            field="cursor",
        ) from exc

    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor is not valid JSON",
            field="cursor",
        ) from exc

    if not isinstance(parsed, dict):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor must decode to a JSON object",
            field="cursor",
        )

    try:
        start_seq = parsed["start_seq"]
        table_value = parsed["table"]
        last_id = parsed["last_id"]
    except KeyError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"cursor missing field {exc.args[0]!r}",
            field="cursor",
        ) from exc

    if not isinstance(start_seq, int) or isinstance(start_seq, bool):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.start_seq must be an integer",
            field="cursor",
        )
    if not isinstance(table_value, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.table must be a string",
            field="cursor",
        )
    if last_id is not None and not isinstance(last_id, str):
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message="cursor.last_id must be a string or null",
            field="cursor",
        )

    try:
        table = InitialSyncTable(table_value)
    except ValueError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"cursor.table {table_value!r} is not a known table",
            field="cursor",
        ) from exc

    return CursorState(start_seq=start_seq, table=table, last_id=last_id)


__all__ = ("CursorState", "InitialSyncTable", "decode_cursor", "encode_cursor")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/sync/test_cursor.py -v`
Expected: PASS — all six tests green.

- [ ] **Step 6: Run lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/sync/_cursor.py tests/sync/test_cursor.py`
Run: `uv run ty check`
Expected: No new violations. If ruff suggests autofixes, accept the safe ones and re-run.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/sync/__init__.py \
        src/py/novamoc/domain/sync/_cursor.py \
        tests/sync/__init__.py \
        tests/sync/test_cursor.py
git commit -m "$(cat <<'EOF'
feat(sync): opaque cursor encode/decode (M2.3)

Cursor encodes (start_seq, table, last_id) as URL-safe base64 JSON.
PayloadShapeError on malformed input — funnels through the existing
ProblemDetailsPlugin as application/problem+json. No HMAC; tampering
only hurts the client.
EOF
)"
```

---

## Task 4: Row-view payloads + discriminated batch envelope

**Files:**
- Create: `src/py/novamoc/domain/sync/_payloads.py`

No new tests — these structs are exercised end-to-end by the paginator and E2E tests in later tasks.

- [ ] **Step 1: Write the payloads module**

Create `src/py/novamoc/domain/sync/_payloads.py`:

```python
"""Wire-format structs for ``GET /sync/initial``.

The response is :class:`InitialSyncBatch`. Its ``body`` field is a
discriminated union tagged on ``table`` — one variant per projection
table — so each batch is a homogeneous list of one shape of row.

Row views deliberately *omit* the derived columns (``properties``,
``name``) from the projection tables: clients reconstruct them by
folding the per-field rows they receive, per ADR-015 §"Derived entity
JSON".

``forbid_unknown_fields=True`` on every struct so a wire-shape drift
shows up loudly in tests rather than silently dropping fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec


class AssetView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``assets`` projected for initial sync.

    Omits ``name`` (mirrors ``col:name``) and ``properties`` (derivable
    from the per-field rows the client also receives).
    """

    id: UUID
    type_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class AssetFieldValueView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``asset_field_values`` projected for initial sync.

    The fold unit. ``hlc`` is preserved so subsequent client-side LWW
    folds against incoming events behave correctly.
    """

    asset_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str


class MaintenanceRecordView(msgspec.Struct, forbid_unknown_fields=True):
    """One row from ``maintenance_records`` projected for initial sync."""

    id: UUID
    type_id: UUID
    asset_id: UUID
    deleted: bool
    row_state_hlc: str
    created_at: datetime
    updated_at: datetime


class MaintenanceRecordFieldValueView(
    msgspec.Struct, forbid_unknown_fields=True
):
    """One row from ``maintenance_record_field_values`` projected for sync."""

    maintenance_record_id: UUID
    field_id: str
    value_json: Any | None
    hlc: str


class _SyncBody(msgspec.Struct, tag_field="table"):
    """Discriminator base for :data:`InitialSyncBody`.

    Subclasses set ``tag`` to the table name. The discriminator field
    is ``table``; msgspec publishes the union as ``oneOf`` in the
    OpenAPI schema.
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
    """One batch of the initial-sync transfer.

    Attributes:
        schema_version: Server's current ``schema_version`` at request
            time. Advances across batches signal a schema change
            mid-transfer; client compares and restarts (ADR-015
            §"Consistency"). Per-batch internal consistency is provided
            by the single-request SQLite WAL snapshot.
        cursor: Opaque continuation. ``None`` ⇒ transfer complete.
            Non-null ⇒ pass back as ``?cursor=`` on the next request.
        event_log_cursor: ``MAX(event_log.seq)`` captured at the start
            of the transfer. Present only when ``cursor`` is ``None``
            (terminal batch); ``None`` on every intermediate batch.
            Client passes this to ``GET /events?cursor=`` to start
            incremental catch-up (M2.4) and as the WS hello cursor (M3).
        body: Discriminated body — one ``items`` list for one projection
            table.
    """

    schema_version: int
    cursor: str | None
    event_log_cursor: int | None
    body: InitialSyncBody


__all__ = (
    "AssetFieldValueView",
    "AssetFieldValuesBatchBody",
    "AssetView",
    "AssetsBatchBody",
    "InitialSyncBatch",
    "InitialSyncBody",
    "MaintenanceRecordFieldValueView",
    "MaintenanceRecordFieldValuesBatchBody",
    "MaintenanceRecordView",
    "MaintenanceRecordsBatchBody",
)
```

- [ ] **Step 2: Sanity-import**

Run: `uv run python -c "from novamoc.domain.sync._payloads import InitialSyncBatch, AssetView; print(InitialSyncBatch.__struct_fields__, AssetView.__struct_fields__)"`
Expected:
```
('schema_version', 'cursor', 'event_log_cursor', 'body') ('id', 'type_id', 'deleted', 'row_state_hlc', 'created_at', 'updated_at')
```

- [ ] **Step 3: Run lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/sync/_payloads.py`
Run: `uv run ty check`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/py/novamoc/domain/sync/_payloads.py
git commit -m "$(cat <<'EOF'
feat(sync): wire-format structs for initial-sync (M2.3)

Row views (Asset/MaintenanceRecord ± their *_field_values) plus the
table-discriminated InitialSyncBatch envelope. name/properties are
omitted from the wire — clients reconstruct from per-field rows
per ADR-015's default.
EOF
)"
```

---

## Task 5: Read-only services for the four projection tables

**Files:**
- Create: `src/py/novamoc/domain/sync/services.py`

No new tests — these are pure advanced-alchemy wrappers identical in shape to `EventLogService`. They're exercised by paginator tests in Task 7+.

- [ ] **Step 1: Write the services module**

Create `src/py/novamoc/domain/sync/services.py`:

```python
"""Read-only service wrappers for the projection tables.

Identical shape to :class:`novamoc.domain.events.services.EventLogService`
— advanced-alchemy repositories over the four projection models. The
write path is the events fold (see ``domain/events/_fold.py``,
``_projection.py``, ``_row_state.py``); these services are used only
by the initial-sync paginator for ordered reads.

Tenant scoping is structural: every ``.list(...)`` goes through Layer 1
of ``db._listeners`` and is filtered to the active tenant.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)


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


class MaintenanceRecordService(
    service.SQLAlchemyAsyncRepositoryService[MaintenanceRecord]
):
    class Repo(repository.SQLAlchemyAsyncRepository[MaintenanceRecord]):
        model_type = MaintenanceRecord

    repository_type = Repo


class MaintenanceRecordFieldValueService(
    service.SQLAlchemyAsyncRepositoryService[MaintenanceRecordFieldValue]
):
    class Repo(repository.SQLAlchemyAsyncRepository[MaintenanceRecordFieldValue]):
        model_type = MaintenanceRecordFieldValue

    repository_type = Repo


__all__ = (
    "AssetFieldValueService",
    "AssetService",
    "MaintenanceRecordFieldValueService",
    "MaintenanceRecordService",
)
```

- [ ] **Step 2: Sanity-import**

Run: `uv run python -c "from novamoc.domain.sync.services import AssetService, AssetFieldValueService, MaintenanceRecordService, MaintenanceRecordFieldValueService; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/sync/services.py`
Run: `uv run ty check`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/py/novamoc/domain/sync/services.py
git commit -m "$(cat <<'EOF'
feat(sync): read-only services for projection tables (M2.3)

Advanced-alchemy wrappers over Asset, AssetFieldValue,
MaintenanceRecord, MaintenanceRecordFieldValue. Used by the
initial-sync paginator; tenant scoping is structural via the
existing Layer 1 listener.
EOF
)"
```

---

## Task 6: Paginator scaffold + fixtures

We split paginator work across multiple tasks (one test scenario per task) so each iteration is reviewable. This task lays down the file, the fixtures, and the simplest test.

**Files:**
- Create: `src/py/novamoc/domain/sync/_pagination.py`
- Create: `tests/sync/test_pagination.py`

- [ ] **Step 1: Write the first failing paginator test**

Create `tests/sync/test_pagination.py`:

```python
"""Unit tests for ``InitialSyncPaginator``.

Run against an in-memory aiosqlite engine — no mocks, per the project's
testing rule. Each test builds its services inline against the
``session`` fixture from ``tests/conftest.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._pagination import InitialSyncPaginator
from novamoc.domain.sync._payloads import AssetsBatchBody
from novamoc.domain.sync.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def paginator(session: AsyncSession) -> InitialSyncPaginator:
    return InitialSyncPaginator(
        change_log_service=SchemaChangeLogService(session=session),
        event_log_service=EventLogService(session=session),
        asset_service=AssetService(session=session),
        asset_field_value_service=AssetFieldValueService(session=session),
        maintenance_record_service=MaintenanceRecordService(session=session),
        maintenance_record_field_value_service=(
            MaintenanceRecordFieldValueService(session=session)
        ),
    )


async def test_empty_tenant_returns_single_terminal_batch(
    paginator: InitialSyncPaginator,
) -> None:
    batch = await paginator(cursor=None, results_per_page=100)
    assert batch.schema_version == 0
    assert batch.cursor is None
    assert batch.event_log_cursor == 0
    assert isinstance(batch.body, AssetsBatchBody)
    assert batch.body.items == ()
```

- [ ] **Step 2: Run test to verify it fails (module doesn't exist)**

Run: `uv run pytest tests/sync/test_pagination.py -v`
Expected: FAIL with `ImportError: cannot import name 'InitialSyncPaginator'`.

- [ ] **Step 3: Write the paginator module**

Create `src/py/novamoc/domain/sync/_pagination.py`:

```python
"""Walks the four projection tables in fixed order.

Captures ``start_seq`` on the first request (when ``cursor is None``),
pages within the current table, advances to the next non-empty table
when the current one runs out, and emits the terminal batch (with
``event_log_cursor=start_seq``) once every table is exhausted.

Tenant scoping is structural: every ``.list(...)`` and every
``current_version`` / ``current_seq`` aggregate routes through Layer 1
of ``db._listeners``. The paginator carries no tenant predicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from sqlalchemy import tuple_

from novamoc.db.models.data import (
    Asset,
    AssetFieldValue,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from novamoc.domain.sync._cursor import (
    CursorState,
    InitialSyncTable,
    decode_cursor,
    encode_cursor,
)
from novamoc.domain.sync._payloads import (
    AssetFieldValuesBatchBody,
    AssetFieldValueView,
    AssetsBatchBody,
    AssetView,
    InitialSyncBatch,
    InitialSyncBody,
    MaintenanceRecordFieldValuesBatchBody,
    MaintenanceRecordFieldValueView,
    MaintenanceRecordsBatchBody,
    MaintenanceRecordView,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from novamoc.domain.events.services import EventLogService
    from novamoc.domain.schema.services import SchemaChangeLogService
    from novamoc.domain.sync.services import (
        AssetFieldValueService,
        AssetService,
        MaintenanceRecordFieldValueService,
        MaintenanceRecordService,
    )


# Fixed order. ``maintenance_record_field_values`` is always last because
# its terminal batch is what carries ``event_log_cursor``.
_TABLES: Final[tuple[InitialSyncTable, ...]] = (
    InitialSyncTable.ASSETS,
    InitialSyncTable.ASSET_FIELD_VALUES,
    InitialSyncTable.MAINTENANCE_RECORDS,
    InitialSyncTable.MAINTENANCE_RECORD_FIELD_VALUES,
)


def _tables_from(start: InitialSyncTable) -> tuple[InitialSyncTable, ...]:
    """Suffix of ``_TABLES`` starting at ``start``."""
    idx = _TABLES.index(start)
    return _TABLES[idx:]


def _split_field_value_last_id(last_id: str) -> tuple[UUID, str]:
    """Decode the ``"<entity_uuid>:<field_id>"`` last-id for field-value tables.

    Splits on the first ``:`` so a ``col:name`` field id (which itself
    contains a colon) survives intact.
    """
    entity_str, _, field_id = last_id.partition(":")
    return UUID(entity_str), field_id


class InitialSyncPaginator:
    """Page through the four projection tables in fixed order."""

    def __init__(
        self,
        *,
        change_log_service: SchemaChangeLogService,
        event_log_service: EventLogService,
        asset_service: AssetService,
        asset_field_value_service: AssetFieldValueService,
        maintenance_record_service: MaintenanceRecordService,
        maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
    ) -> None:
        self._change_log = change_log_service
        self._event_log = event_log_service
        self._asset = asset_service
        self._asset_field_value = asset_field_value_service
        self._maintenance_record = maintenance_record_service
        self._maintenance_record_field_value = maintenance_record_field_value_service

    async def __call__(
        self, *, cursor: str | None, results_per_page: int
    ) -> InitialSyncBatch:
        if cursor is None:
            start_seq = await self._event_log.current_seq()
            current_table = _TABLES[0]
            last_id: str | None = None
        else:
            state = decode_cursor(cursor)
            start_seq = state.start_seq
            current_table = state.table
            last_id = state.last_id

        schema_version = await self._change_log.current_version()

        for table in _tables_from(current_table):
            page_last_id = last_id if table is current_table else None
            rows = await self._read_page(table, page_last_id, results_per_page + 1)
            has_more_in_table = len(rows) > results_per_page
            page_rows = rows[:results_per_page]
            if page_rows or table is _TABLES[-1]:
                body = _body_for(table, page_rows)
                next_cursor, event_log_cursor = self._compute_continuation(
                    table=table,
                    page_rows=page_rows,
                    has_more_in_table=has_more_in_table,
                    start_seq=start_seq,
                )
                return InitialSyncBatch(
                    schema_version=schema_version,
                    cursor=next_cursor,
                    event_log_cursor=event_log_cursor,
                    body=body,
                )
        # Unreachable: the last-table branch above always returns.
        msg = "InitialSyncPaginator exited the walk without emitting a batch"
        raise RuntimeError(msg)

    async def _read_page(
        self,
        table: InitialSyncTable,
        last_id: str | None,
        limit: int,
    ) -> Sequence[object]:
        if table is InitialSyncTable.ASSETS:
            filters: list[object] = [
                OrderBy(field_name="id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                filters.insert(0, Asset.id > UUID(last_id))
            return await self._asset.list(*filters)
        if table is InitialSyncTable.ASSET_FIELD_VALUES:
            filters = [
                OrderBy(field_name="asset_id"),
                OrderBy(field_name="field_id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                entity_uuid, field_id = _split_field_value_last_id(last_id)
                filters.insert(
                    0,
                    tuple_(AssetFieldValue.asset_id, AssetFieldValue.field_id)
                    > tuple_(entity_uuid, field_id),
                )
            return await self._asset_field_value.list(*filters)
        if table is InitialSyncTable.MAINTENANCE_RECORDS:
            filters = [
                OrderBy(field_name="id"),
                LimitOffset(limit=limit, offset=0),
            ]
            if last_id is not None:
                filters.insert(0, MaintenanceRecord.id > UUID(last_id))
            return await self._maintenance_record.list(*filters)
        # MAINTENANCE_RECORD_FIELD_VALUES
        filters = [
            OrderBy(field_name="maintenance_record_id"),
            OrderBy(field_name="field_id"),
            LimitOffset(limit=limit, offset=0),
        ]
        if last_id is not None:
            entity_uuid, field_id = _split_field_value_last_id(last_id)
            filters.insert(
                0,
                tuple_(
                    MaintenanceRecordFieldValue.maintenance_record_id,
                    MaintenanceRecordFieldValue.field_id,
                )
                > tuple_(entity_uuid, field_id),
            )
        return await self._maintenance_record_field_value.list(*filters)

    @staticmethod
    def _compute_continuation(
        *,
        table: InitialSyncTable,
        page_rows: Sequence[object],
        has_more_in_table: bool,
        start_seq: int,
    ) -> tuple[str | None, int | None]:
        """Return ``(next_cursor, event_log_cursor)`` for this batch."""
        if has_more_in_table:
            next_state = CursorState(
                start_seq=start_seq,
                table=table,
                last_id=_last_id_of(table, page_rows[-1]),
            )
            return encode_cursor(next_state), None
        if table is _TABLES[-1]:
            return None, start_seq
        next_table = _TABLES[_TABLES.index(table) + 1]
        next_state = CursorState(
            start_seq=start_seq, table=next_table, last_id=None
        )
        return encode_cursor(next_state), None


def _last_id_of(table: InitialSyncTable, row: object) -> str:
    """Return the encoded last-id string for ``row`` in ``table``."""
    if table is InitialSyncTable.ASSETS:
        return str(row.id)  # type: ignore[attr-defined]
    if table is InitialSyncTable.ASSET_FIELD_VALUES:
        return f"{row.asset_id}:{row.field_id}"  # type: ignore[attr-defined]
    if table is InitialSyncTable.MAINTENANCE_RECORDS:
        return str(row.id)  # type: ignore[attr-defined]
    return f"{row.maintenance_record_id}:{row.field_id}"  # type: ignore[attr-defined]


def _body_for(
    table: InitialSyncTable, rows: Sequence[object]
) -> InitialSyncBody:
    """Wrap ``rows`` in the discriminated body variant for ``table``."""
    if table is InitialSyncTable.ASSETS:
        return AssetsBatchBody(
            items=tuple(
                AssetView(
                    id=r.id,  # type: ignore[attr-defined]
                    type_id=r.type_id,  # type: ignore[attr-defined]
                    deleted=r.deleted,  # type: ignore[attr-defined]
                    row_state_hlc=r.row_state_hlc,  # type: ignore[attr-defined]
                    created_at=r.created_at,  # type: ignore[attr-defined]
                    updated_at=r.updated_at,  # type: ignore[attr-defined]
                )
                for r in rows
            )
        )
    if table is InitialSyncTable.ASSET_FIELD_VALUES:
        return AssetFieldValuesBatchBody(
            items=tuple(
                AssetFieldValueView(
                    asset_id=r.asset_id,  # type: ignore[attr-defined]
                    field_id=r.field_id,  # type: ignore[attr-defined]
                    value_json=r.value_json,  # type: ignore[attr-defined]
                    hlc=r.hlc,  # type: ignore[attr-defined]
                )
                for r in rows
            )
        )
    if table is InitialSyncTable.MAINTENANCE_RECORDS:
        return MaintenanceRecordsBatchBody(
            items=tuple(
                MaintenanceRecordView(
                    id=r.id,  # type: ignore[attr-defined]
                    type_id=r.type_id,  # type: ignore[attr-defined]
                    asset_id=r.asset_id,  # type: ignore[attr-defined]
                    deleted=r.deleted,  # type: ignore[attr-defined]
                    row_state_hlc=r.row_state_hlc,  # type: ignore[attr-defined]
                    created_at=r.created_at,  # type: ignore[attr-defined]
                    updated_at=r.updated_at,  # type: ignore[attr-defined]
                )
                for r in rows
            )
        )
    return MaintenanceRecordFieldValuesBatchBody(
        items=tuple(
            MaintenanceRecordFieldValueView(
                maintenance_record_id=r.maintenance_record_id,  # type: ignore[attr-defined]
                field_id=r.field_id,  # type: ignore[attr-defined]
                value_json=r.value_json,  # type: ignore[attr-defined]
                hlc=r.hlc,  # type: ignore[attr-defined]
            )
            for r in rows
        )
    )


__all__ = ("InitialSyncPaginator",)
```

- [ ] **Step 4: Run the empty-tenant test**

Run: `uv run pytest tests/sync/test_pagination.py -v`
Expected: PASS — the single test for empty tenant.

- [ ] **Step 5: Run lint + type-check**

Run: `uv run ruff check src/py/novamoc/domain/sync/_pagination.py tests/sync/test_pagination.py`
Run: `uv run ty check`
Expected: clean (the `# type: ignore[attr-defined]` comments are intentional — the helper functions take `object` to avoid four overloads).

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/sync/_pagination.py tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
feat(sync): InitialSyncPaginator scaffold + empty-tenant test (M2.3)

Captures start_seq on first request (cursor=None), reads each table
with ordered limit-offset, skips empty intermediates, emits the
terminal batch with event_log_cursor=start_seq on the last table.
First test asserts empty tenant returns a single terminal batch.
EOF
)"
```

---

## Task 7: Paginator — single table fits one page

**Files:**
- Modify: `tests/sync/test_pagination.py`

Helper note: we'll author rows directly via the session (bypassing event-fold complexity) — the paginator under test only reads, so seeded rows work. We use a tiny helper to keep test bodies readable.

- [ ] **Step 1: Add the helper and the test**

Append to `tests/sync/test_pagination.py` (above the test functions, after the existing fixture):

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from novamoc.db.models.data import Asset
from novamoc.db.models.schema import AssetType
from novamoc.domain.sync._payloads import AssetsBatchBody


async def _make_asset_type(
    session: AsyncSession, name: str = "Truck", tenant_id: str = "t1"
) -> AssetType:
    asset_type = AssetType(
        id=uuid4(), tenant_id=tenant_id, name=name, active=True
    )
    session.add(asset_type)
    await session.flush()
    return asset_type


async def _make_asset(
    session: AsyncSession,
    *,
    type_id: UUID,
    tenant_id: str = "t1",
    deleted: bool = False,
    hlc: str = "0001700000000000-00000-abc",
) -> Asset:
    asset = Asset(
        id=uuid4(),
        tenant_id=tenant_id,
        type_id=type_id,
        name=None,
        properties={},
        deleted=deleted,
        row_state_hlc=hlc,
    )
    session.add(asset)
    await session.flush()
    return asset


async def test_single_table_fits_one_page(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    for _ in range(3):
        await _make_asset(session, type_id=asset_type.id)

    batch = await paginator(cursor=None, results_per_page=100)
    assert isinstance(batch.body, AssetsBatchBody)
    assert len(batch.body.items) == 3
    assert batch.cursor is None
    assert batch.event_log_cursor == 0
```

Also ensure the imports at the top of the file include the additions. The earlier import block already imports `AssetsBatchBody`; if it does not, add it. The new imports (`UTC`, `datetime`, `uuid4`, `Asset`, `AssetType`) must be added.

If you find AssetType under `novamoc.db.models.schema` does not export by that name, use:

```python
from novamoc.db.models import schema as schema_models
# then schema_models.AssetType
```

Check by running: `uv run python -c "from novamoc.db.models.schema import AssetType; print('ok')"`.

- [ ] **Step 2: Run the new test**

Run: `uv run pytest tests/sync/test_pagination.py::test_single_table_fits_one_page -v`
Expected: PASS.

- [ ] **Step 3: Run the full pagination test file**

Run: `uv run pytest tests/sync/test_pagination.py -v`
Expected: both tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): single-table-fits-one-page paginator case (M2.3)

3 assets, page=100 ⇒ one terminal batch with 3 items, cursor=null,
event_log_cursor=0 (no events seeded yet).
EOF
)"
```

---

## Task 8: Paginator — multi-page within one table

**Files:**
- Modify: `tests/sync/test_pagination.py`

- [ ] **Step 1: Append the test**

Append to `tests/sync/test_pagination.py`:

```python
async def test_multi_page_within_one_table(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    asset_ids = {(await _make_asset(session, type_id=asset_type.id)).id for _ in range(5)}

    seen_ids: set[UUID] = set()
    cursor: str | None = None
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=2)
        assert isinstance(batch.body, AssetsBatchBody)
        for item in batch.body.items:
            assert item.id not in seen_ids, "no duplicates across pages"
            seen_ids.add(item.id)
        pages += 1
        if batch.cursor is None:
            assert batch.event_log_cursor == 0
            break
        cursor = batch.cursor
        assert pages < 10, "guard against runaway loop"

    assert seen_ids == asset_ids
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_multi_page_within_one_table -v`
Expected: PASS. The paginator advances within ``assets`` using `last_id` until the table is exhausted, then advances through the three empty later tables (collapsed server-side) and emits the terminal batch.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator multi-page cursor handoff within one table (M2.3)

5 assets, page=2 ⇒ multiple non-terminal batches each cap-sized,
final terminal batch caps off; no duplicates, full coverage.
EOF
)"
```

---

## Task 9: Paginator — cross-table walk with all four populated

**Files:**
- Modify: `tests/sync/test_pagination.py`

- [ ] **Step 1: Append helpers + test**

Append to `tests/sync/test_pagination.py`:

```python
from novamoc.db.models.data import (
    AssetFieldValue,
    EventLog,
    EventOp,
    MaintenanceRecord,
    MaintenanceRecordFieldValue,
)
from novamoc.db.models.schema import MaintenanceRecordType
from novamoc.domain.sync._payloads import (
    AssetFieldValuesBatchBody,
    MaintenanceRecordFieldValuesBatchBody,
    MaintenanceRecordsBatchBody,
)


async def _make_maintenance_record_type(
    session: AsyncSession, name: str = "Inspection", tenant_id: str = "t1"
) -> MaintenanceRecordType:
    mrt = MaintenanceRecordType(
        id=uuid4(), tenant_id=tenant_id, name=name, active=True
    )
    session.add(mrt)
    await session.flush()
    return mrt


async def _make_event(
    session: AsyncSession,
    *,
    tenant_id: str = "t1",
    hlc: str,
    type_id: UUID,
    entity_id: UUID,
    schema_version: int = 0,
) -> None:
    session.add(
        EventLog(
            tenant_id=tenant_id,
            hlc=hlc,
            schema_version=schema_version,
            table_name="assets",
            type_id=str(type_id),
            entity_id=str(entity_id),
            field_id=None,
            op=EventOp.SET,
            value_json={"event": "created", "parent": None, "values": {}},
            received_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def test_cross_table_walk(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    mr_type = await _make_maintenance_record_type(session)
    asset = await _make_asset(session, type_id=asset_type.id)

    # asset_field_values row
    session.add(
        AssetFieldValue(
            tenant_id="t1",
            asset_id=asset.id,
            field_id="col:name",
            value_json="Truck-1",
            hlc="0001700000000000-00000-abc",
        )
    )
    # maintenance_record + maintenance_record_field_values
    mr = MaintenanceRecord(
        id=uuid4(),
        tenant_id="t1",
        type_id=mr_type.id,
        asset_id=asset.id,
        name=None,
        properties={},
        deleted=False,
        row_state_hlc="0001700000000001-00000-abc",
    )
    session.add(mr)
    await session.flush()
    session.add(
        MaintenanceRecordFieldValue(
            tenant_id="t1",
            maintenance_record_id=mr.id,
            field_id="col:name",
            value_json="Inspection-A",
            hlc="0001700000000001-00000-abc",
        )
    )
    # One event so event_log_cursor is non-zero
    await _make_event(
        session,
        hlc="0001700000000002-00000-abc",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    visited: list[type] = []
    cursor: str | None = None
    while True:
        batch = await paginator(cursor=cursor, results_per_page=10)
        visited.append(type(batch.body))
        if batch.cursor is None:
            assert batch.event_log_cursor == 1  # one event seeded
            break
        cursor = batch.cursor

    assert visited == [
        AssetsBatchBody,
        AssetFieldValuesBatchBody,
        MaintenanceRecordsBatchBody,
        MaintenanceRecordFieldValuesBatchBody,
    ]
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_cross_table_walk -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator cross-table walk with all four populated (M2.3)

Seeds 1 row per projection table + 1 event. Drives the paginator to
completion and asserts the visited body-type sequence is exactly
(assets → asset_field_values → maintenance_records →
maintenance_record_field_values) and event_log_cursor matches the
seeded seq.
EOF
)"
```

---

## Task 10: Paginator — skip empty intermediate tables

**Files:**
- Modify: `tests/sync/test_pagination.py`

- [ ] **Step 1: Append the test**

```python
async def test_skips_empty_intermediate_tables(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    mr_type = await _make_maintenance_record_type(session)
    # Assets populated, asset_field_values EMPTY, maintenance_records populated.
    asset = await _make_asset(session, type_id=asset_type.id)
    mr = MaintenanceRecord(
        id=uuid4(),
        tenant_id="t1",
        type_id=mr_type.id,
        asset_id=asset.id,
        name=None,
        properties={},
        deleted=False,
        row_state_hlc="0001700000000001-00000-abc",
    )
    session.add(mr)
    await session.flush()

    visited: list[type] = []
    cursor: str | None = None
    while True:
        batch = await paginator(cursor=cursor, results_per_page=10)
        visited.append(type(batch.body))
        if batch.cursor is None:
            break
        cursor = batch.cursor

    assert AssetFieldValuesBatchBody not in visited
    assert AssetsBatchBody in visited
    assert MaintenanceRecordsBatchBody in visited
    # Last table is always emitted even if empty:
    assert visited[-1] is MaintenanceRecordFieldValuesBatchBody
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_skips_empty_intermediate_tables -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator skips empty intermediate tables (M2.3)

asset_field_values empty between populated assets and maintenance
records ⇒ no batch with body=AssetFieldValuesBatchBody is emitted.
Confirms the in-request "advance to next table when current is empty"
collapse. The last table is always emitted (possibly empty) so the
terminal event_log_cursor still rides.
EOF
)"
```

---

## Task 11: Paginator — start_seq is start-snapshot

**Files:**
- Modify: `tests/sync/test_pagination.py`

This is the correctness-critical test (see design spec §"Why `start_seq` on the first request"). If this fails, the implementation has the silent-skip bug.

- [ ] **Step 1: Append the test**

```python
async def test_start_seq_is_captured_at_first_request(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    asset = await _make_asset(session, type_id=asset_type.id)
    await _make_event(
        session,
        hlc="0001700000000000-00000-aaa",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    # First request — cursor=None — captures start_seq = current MAX(seq).
    batch1 = await paginator(cursor=None, results_per_page=1)
    assert batch1.cursor is not None
    # Insert a new event AFTER start_seq is captured.
    await _make_event(
        session,
        hlc="0001700000000001-00000-bbb",
        type_id=asset_type.id,
        entity_id=asset.id,
    )

    # Drive to terminal and check the cursor is the pre-extra seq.
    cursor: str | None = batch1.cursor
    final: int | None = None
    pages = 0
    while True:
        batch = await paginator(cursor=cursor, results_per_page=1)
        if batch.cursor is None:
            final = batch.event_log_cursor
            break
        cursor = batch.cursor
        pages += 1
        assert pages < 20, "guard"

    # The extra event raised MAX(seq) to 2, but the threaded start_seq is 1.
    assert final == 1
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_start_seq_is_captured_at_first_request -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator captures start_seq at first request (M2.3)

Inserts a new event between the first request and the terminal one;
asserts the threaded start_seq is the pre-extra value, not the
post-extra value. This is the correctness guarantee for mid-transfer
event arrivals (design spec §"Why start_seq on the first request").
EOF
)"
```

---

## Task 12: Paginator — schema_version is current at request time

**Files:**
- Modify: `tests/sync/test_pagination.py`

- [ ] **Step 1: Append the test**

```python
from novamoc.db.models.schema import SchemaChangeLog
from novamoc.domain.schema._commands import SchemaCommand


async def _bump_schema_version(
    session: AsyncSession, tenant_id: str = "t1"
) -> int:
    """Append a no-op schema_change_log row to bump current_version()."""
    # Compute next seq by reading current max for the tenant.
    from sqlalchemy import func, select

    current = await session.execute(
        select(func.coalesce(func.max(SchemaChangeLog.seq), 0)).where(
            SchemaChangeLog.tenant_id == tenant_id
        )
    )
    next_seq = int(current.scalar_one()) + 1
    session.add(
        SchemaChangeLog(
            tenant_id=tenant_id,
            seq=next_seq,
            command=str(SchemaCommand.CREATE_ASSET_TYPE.value),
            entity_id=uuid4(),
            payload={"name": "Truck"},
        )
    )
    await session.flush()
    return next_seq


async def test_schema_version_is_current_each_request(
    session: AsyncSession,
    paginator: InitialSyncPaginator,
) -> None:
    asset_type = await _make_asset_type(session)
    for _ in range(3):
        await _make_asset(session, type_id=asset_type.id)
    v1 = await _bump_schema_version(session)

    batch1 = await paginator(cursor=None, results_per_page=1)
    assert batch1.schema_version == v1

    v2 = await _bump_schema_version(session)
    assert v2 > v1

    batch2 = await paginator(cursor=batch1.cursor, results_per_page=1)
    assert batch2.schema_version == v2
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_schema_version_is_current_each_request -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator schema_version is current at request time (M2.3)

Server emits the current schema_version on every batch (does not
snapshot start-time version). Bumping the version between batches is
observable in the next response — the client compares and decides
whether to restart.
EOF
)"
```

---

## Task 13: Paginator — bad cursor surfaces PayloadShapeError

**Files:**
- Modify: `tests/sync/test_pagination.py`

- [ ] **Step 1: Append the test**

```python
async def test_bad_cursor_raises_payload_shape_error(
    paginator: InitialSyncPaginator,
) -> None:
    with pytest.raises(PayloadShapeError) as exc:
        await paginator(cursor="not-base64!@#", results_per_page=10)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


from novamoc.domain._errors import ErrorCode, PayloadShapeError  # noqa: E402
```

(Placing the import at the bottom keeps the test-file additions self-contained per task. Move them to the top in any later test-file cleanup task — fine as-is for now.)

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_pagination.py::test_bad_cursor_raises_payload_shape_error -v`
Expected: PASS.

- [ ] **Step 3: Run the full paginator suite**

Run: `uv run pytest tests/sync/test_pagination.py -v`
Expected: all paginator tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/sync/test_pagination.py
git commit -m "$(cat <<'EOF'
test(sync): paginator surfaces bad cursor as PayloadShapeError (M2.3)

Verifies the decode_cursor → PayloadShapeError contract at the
paginator boundary, which is what the controller relies on for its
400 application/problem+json mapping.
EOF
)"
```

---

## Task 14: Controller + asgi registration

**Files:**
- Create: `src/py/novamoc/domain/sync/controllers/__init__.py`
- Create: `src/py/novamoc/domain/sync/controllers/_sync.py`
- Modify: `src/py/novamoc/asgi.py`

- [ ] **Step 1: Write the controller package init**

Create `src/py/novamoc/domain/sync/controllers/__init__.py`:

```python
from ._sync import SyncController

__all__ = ("SyncController",)
```

- [ ] **Step 2: Write the controller**

Create `src/py/novamoc/domain/sync/controllers/_sync.py`:

```python
"""HTTP controller for ``/sync/initial`` (M2.3, ADR-015).

Thin by design: bound checking lives in the Litestar ``Parameter(...)``
annotation, cursor decoding lives in the paginator, tenant scoping is
structural via the listener layer. The handler performs no manual
error mapping; ``ValidationException`` and ``PayloadShapeError`` both
funnel through the existing ``ProblemDetailsPlugin`` (ADR-016).
"""

from __future__ import annotations

from typing import Annotated

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, get
from litestar.di import Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from novamoc.api._problem_details import ProblemDetails
from novamoc.config import (
    INITIAL_SYNC_DEFAULT_BATCH_SIZE,
    INITIAL_SYNC_MAX_BATCH_SIZE,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import SchemaChangeLogService
from novamoc.domain.sync._pagination import InitialSyncPaginator
from novamoc.domain.sync._payloads import InitialSyncBatch
from novamoc.domain.sync.services import (
    AssetFieldValueService,
    AssetService,
    MaintenanceRecordFieldValueService,
    MaintenanceRecordService,
)


async def _provide_initial_sync_paginator(  # noqa: PLR0913  # one parameter per DI'd dep; Litestar pattern
    schema_change_log_service: SchemaChangeLogService,
    event_log_service: EventLogService,
    asset_service: AssetService,
    asset_field_value_service: AssetFieldValueService,
    maintenance_record_service: MaintenanceRecordService,
    maintenance_record_field_value_service: MaintenanceRecordFieldValueService,
) -> InitialSyncPaginator:
    return InitialSyncPaginator(
        change_log_service=schema_change_log_service,
        event_log_service=event_log_service,
        asset_service=asset_service,
        asset_field_value_service=asset_field_value_service,
        maintenance_record_service=maintenance_record_service,
        maintenance_record_field_value_service=maintenance_record_field_value_service,
    )


class SyncController(Controller):
    path = "/sync"
    tags = ("sync",)
    dependencies = (
        {"paginator": Provide(_provide_initial_sync_paginator)}
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
        | providers.create_service_dependencies(
            EventLogService, "event_log_service"
        )
        | providers.create_service_dependencies(AssetService, "asset_service")
        | providers.create_service_dependencies(
            AssetFieldValueService, "asset_field_value_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordService, "maintenance_record_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordFieldValueService,
            "maintenance_record_field_value_service",
        )
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

- [ ] **Step 3: Register the controller in `asgi.py`**

Edit `src/py/novamoc/asgi.py`:

In the import section inside `create_app` (around line 52-54), find:

```python
from novamoc.domain.events.controllers import EventsController
from novamoc.domain.schema.controllers import SchemaController
```

Add a new line:

```python
from novamoc.domain.sync.controllers import SyncController
```

Then in the `Litestar(...)` call (around line 95), change:

```python
route_handlers=[SchemaController, EventsController, problem_docs_router],
```

to:

```python
route_handlers=[SchemaController, EventsController, SyncController, problem_docs_router],
```

- [ ] **Step 4: Smoke-test the app boots**

Run: `uv run python -c "from novamoc.asgi import create_app; from novamoc.config import Settings; create_app(Settings()); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Run lint + type-check + existing test suite**

Run: `uv run ruff check src/py/novamoc/domain/sync/`
Run: `uv run ty check`
Run: `uv run pytest -q`
Expected: clean lint, clean type-check, all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/sync/controllers/ src/py/novamoc/asgi.py
git commit -m "$(cat <<'EOF'
feat(sync): SyncController mounted at /sync/initial (M2.3)

Thin handler — DI-injected InitialSyncPaginator + Litestar
Parameter(ge=1, le=5000) for the page-size bound. Errors funnel
through the existing ProblemDetailsPlugin: validation -> 400, bad
cursor -> 400 via PayloadShapeError (INVALID_PAYLOAD_SHAPE).
Registered in asgi.create_app alongside SchemaController and
EventsController.
EOF
)"
```

---

## Task 15: E2E — empty tenant

**Files:**
- Create: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Write the empty-tenant test**

Create `tests/sync/test_endpoint_sync_initial.py`:

```python
"""End-to-end tests for ``GET /sync/initial`` (M2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_empty_tenant_returns_terminal_batch(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/sync/initial")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 0
    assert body["cursor"] is None
    assert body["event_log_cursor"] == 0
    assert body["body"]["table"] == "assets"
    assert body["body"]["items"] == []
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): GET /sync/initial empty tenant returns terminal batch (M2.3)

200 OK with cursor=null, event_log_cursor=0, body.table=assets,
body.items=[]. Single round-trip for an empty tenant.
EOF
)"
```

---

## Task 16: E2E — single round-trip with seeded data

**Files:**
- Modify: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Append the test**

```python
from uuid import uuid4


async def test_post_event_then_get_sync_initial_round_trip(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())
    post = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000000-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {
                        "event": "created",
                        "values": {"col:name": "Truck-1"},
                    },
                }
            ],
        },
    )
    assert post.status_code == 202, post.text

    # Drive sync to completion, accumulating items by table.
    items_by_table: dict[str, list[dict]] = {}
    cursor: str | None = None
    while True:
        params = {"results_per_page": "100"}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/sync/initial", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        table = body["body"]["table"]
        items_by_table.setdefault(table, []).extend(body["body"]["items"])
        if body["cursor"] is None:
            assert body["event_log_cursor"] >= 1
            break
        cursor = body["cursor"]

    # Exactly one asset, with the instance_id we POSTed.
    assert len(items_by_table.get("assets", [])) == 1
    asset = items_by_table["assets"][0]
    assert asset["id"] == instance_id
    assert asset["type_id"] == type_id
    assert asset["deleted"] is False
    assert "row_state_hlc" in asset

    # At least one asset_field_values row for col:name = "Truck-1".
    fvs = items_by_table.get("asset_field_values", [])
    name_fv = next(
        (r for r in fvs if r["asset_id"] == instance_id and r["field_id"] == "col:name"),
        None,
    )
    assert name_fv is not None, fvs
    assert name_fv["value_json"] == "Truck-1"
    assert name_fv["hlc"] == "0001700000000000-00000-abc"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py::test_post_event_then_get_sync_initial_round_trip -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): POST /events + GET /sync/initial round trip (M2.3)

POST a Created asset event, drive GET /sync/initial to terminal,
assert the asset and its col:name field-value row both surface with
HLC preserved.
EOF
)"
```

---

## Task 17: E2E — multi-batch round-trip

**Files:**
- Modify: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Append the test**

```python
async def test_multi_batch_round_trip(client: AsyncTestClient) -> None:
    type_id = str(uuid4())
    instance_ids = [str(uuid4()) for _ in range(5)]
    for i, iid in enumerate(instance_ids):
        post = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": f"00017000000000{i:02d}-00000-abc",
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": iid,
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert post.status_code == 202, post.text

    seen_asset_ids: set[str] = set()
    cursor: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "2"}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/sync/initial", params=params)
        body = resp.json()
        if body["body"]["table"] == "assets":
            for r in body["body"]["items"]:
                assert r["id"] not in seen_asset_ids, "duplicates across pages"
                seen_asset_ids.add(r["id"])
        if body["cursor"] is None:
            break
        cursor = body["cursor"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    assert seen_asset_ids == set(instance_ids)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py::test_multi_batch_round_trip -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): GET /sync/initial multi-batch round-trip (M2.3)

5 assets posted, page=2 ⇒ multiple round-trips. Every asset id
surfaces exactly once across the assembled batches.
EOF
)"
```

---

## Task 18: E2E — mid-transfer schema-version observation

**Files:**
- Modify: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Append the test**

```python
async def test_mid_transfer_schema_version_advance_is_observable(
    client: AsyncTestClient,
) -> None:
    # Seed enough assets to force a multi-batch transfer.
    type_id = str(uuid4())
    for i in range(3):
        post = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": f"00017000000000{i:02d}-00000-abc",
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": str(uuid4()),
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert post.status_code == 202, post.text

    # First batch — observe schema_version V1.
    resp1 = await client.get("/sync/initial", params={"results_per_page": "1"})
    body1 = resp1.json()
    v1 = body1["schema_version"]
    assert body1["cursor"] is not None

    # Commit a schema change.
    schema_resp = await client.post(
        "/schema",
        json={"type": "create_asset_type", "name": "Truck"},
    )
    assert schema_resp.status_code in (200, 201), schema_resp.text

    # Next batch (driven by body1.cursor) — observe a higher schema_version.
    resp2 = await client.get(
        "/sync/initial",
        params={"cursor": body1["cursor"], "results_per_page": "1"},
    )
    body2 = resp2.json()
    assert body2["schema_version"] > v1
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py::test_mid_transfer_schema_version_advance_is_observable -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): mid-transfer schema_version advance is observable (M2.3)

Page 1 reports V1, commit a schema change, page 2 reports V2 > V1.
The server emits the current schema_version on every batch; the
client-side restart decision is out of scope.
EOF
)"
```

---

## Task 19: E2E — validation errors (bad cursor, bad page size)

**Files:**
- Modify: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Append the tests**

```python
async def test_bad_cursor_returns_problem_details(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/sync/initial", params={"cursor": "not-base64!@#"})
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].rstrip("/").endswith("invalid_payload_shape")


async def test_results_per_page_below_min_is_400(client: AsyncTestClient) -> None:
    resp = await client.get("/sync/initial", params={"results_per_page": "0"})
    assert resp.status_code == 400, resp.text


async def test_results_per_page_above_max_is_400(client: AsyncTestClient) -> None:
    resp = await client.get(
        "/sync/initial", params={"results_per_page": "5001"}
    )
    assert resp.status_code == 400, resp.text
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py -v -k "bad_cursor or results_per_page"`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): validation errors as application/problem+json (M2.3)

Bad cursor → 400 invalid_payload_shape (via PayloadShapeError).
results_per_page out of range → 400 (via Litestar ValidationException).
Both render through the existing ProblemDetailsPlugin.
EOF
)"
```

---

## Task 20: E2E — tombstone inclusion

**Files:**
- Modify: `tests/sync/test_endpoint_sync_initial.py`

- [ ] **Step 1: Append the test**

```python
async def test_tombstoned_assets_are_included(client: AsyncTestClient) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())

    create = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000000-00000-aaa",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert create.status_code == 202, create.text

    deact = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000001-00000-aaa",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "deactivated"},
                }
            ],
        },
    )
    assert deact.status_code == 202, deact.text

    seen_assets: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"results_per_page": "100"}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get("/sync/initial", params=params)).json()
        if body["body"]["table"] == "assets":
            seen_assets.extend(body["body"]["items"])
        if body["cursor"] is None:
            break
        cursor = body["cursor"]

    target = next(a for a in seen_assets if a["id"] == instance_id)
    assert target["deleted"] is True
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/sync/test_endpoint_sync_initial.py::test_tombstoned_assets_are_included -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sync/test_endpoint_sync_initial.py
git commit -m "$(cat <<'EOF'
test(sync): tombstoned assets surface with deleted=true (M2.3)

Per ADR-015, tombstones ride in the projection transfer so clients
render row-state correctly. Created → Deactivated then sync; the
returned AssetView carries deleted=true.
EOF
)"
```

---

## Task 21: Cross-tenant isolation

**Files:**
- Create: `tests/sync/test_sync_cross_tenant_isolation.py`

We need a second tenant token. Re-use the same pattern as
`tests/events/test_catchup_cross_tenant_isolation.py` — look there for
the per-tenant fixture wiring (likely an additional dev token, or
parametrising the auth header).

- [ ] **Step 1: Inspect the events cross-tenant test for the pattern**

Run: `cat tests/events/test_catchup_cross_tenant_isolation.py`
Note how it sets up t-a / t-b: which fixture provides multi-tenant tokens, how it switches `client.headers["Authorization"]` per tenant, and how it seeds.

- [ ] **Step 2: Write the cross-tenant test**

Create `tests/sync/test_sync_cross_tenant_isolation.py`. Follow the structure of `tests/events/test_catchup_cross_tenant_isolation.py` exactly; the only differences are the endpoint (`/sync/initial` instead of `/events/`) and the body shape (paginated `body.items` per table instead of flat `items`).

The test must:
- Seed equivalent data under `t-a` and `t-b` (e.g., one asset each, with distinct ids).
- Drive `/sync/initial` to completion under each tenant.
- Assert each tenant sees only its own asset ids; no cross-pollination.

Concrete skeleton (adapt the auth setup to whatever the events isolation test uses):

```python
"""Cross-tenant isolation for ``GET /sync/initial`` (M2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def _drive_sync(client: AsyncTestClient) -> dict[str, list[dict]]:
    items_by_table: dict[str, list[dict]] = {}
    cursor: str | None = None
    while True:
        params = {"results_per_page": "100"}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/sync/initial", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        table = body["body"]["table"]
        items_by_table.setdefault(table, []).extend(body["body"]["items"])
        if body["cursor"] is None:
            return items_by_table
        cursor = body["cursor"]


async def test_each_tenant_sees_only_its_own_assets(
    client: AsyncTestClient,
    # … any additional fixtures the events isolation test uses for
    # second-tenant tokens / setup …
) -> None:
    # 1. Seed an asset under t-a (via POST /events with the t-a bearer).
    # 2. Switch auth header to t-b; seed a distinct asset.
    # 3. Drive /sync/initial under each header; assert ids are partitioned.
    ...  # adapt to the events isolation pattern
```

If `tests/events/test_catchup_cross_tenant_isolation.py` uses session-level fixtures (e.g., `t_a_client`, `t_b_client`), reuse those — define them in `tests/conftest.py` if they're already there, or co-locate per-file.

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/sync/test_sync_cross_tenant_isolation.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/sync/test_sync_cross_tenant_isolation.py
git commit -m "$(cat <<'EOF'
test(sync): cross-tenant isolation for /sync/initial (M2.3)

t-a and t-b seeded with distinct assets; each sees only its own data
through the paginator. The tenant predicate is supplied structurally
by Layer 1 of db._listeners on every ORM read.
EOF
)"
```

---

## Task 22: CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md` — add a new "Initial sync endpoint (`GET /sync/initial`)" subsection after the existing "Events catch-up endpoint (`GET /events`)" subsection.

- [ ] **Step 1: Locate the insertion point**

Open `CLAUDE.md`. Find the heading `## Events catch-up endpoint (`GET /events`)`. Place the new subsection immediately after that subsection ends — before the next `##` heading (`## Data model conventions`).

- [ ] **Step 2: Write the new subsection**

Insert the following into `CLAUDE.md`:

````markdown
## Initial sync endpoint (`GET /sync/initial`)

Companion to ``GET /events`` and the bulk half of the sync handshake
(ADR-015). Streams the active tenant's current data-projection state —
``assets``, ``asset_field_values``, ``maintenance_records``,
``maintenance_record_field_values`` — in fixed-table-order batches with
an opaque continuation ``cursor``. Closes M2.3 (issue #33).

Response shape is a custom envelope (not Litestar's ``CursorPagination``
— items are heterogeneous across batches):

```
InitialSyncBatch {
  schema_version: int
  cursor: str | null         # opaque continuation; null = transfer complete
  event_log_cursor: int | null  # only when cursor is null (terminal batch)
  body: InitialSyncBody      # discriminated by `table` (msgspec tag_field)
}
```

``InitialSyncBody`` is a tagged union with one variant per projection
table: ``AssetsBatchBody``, ``AssetFieldValuesBatchBody``,
``MaintenanceRecordsBatchBody``, ``MaintenanceRecordFieldValuesBatchBody``.
Each variant carries an ``items`` tuple of the corresponding row view.
Row views deliberately omit ``name`` (mirrors ``col:name`` in field
values) and ``properties`` (derivable from per-field rows) — the client
reconstructs them by folding field-value rows, per ADR-015 §"Derived
entity JSON".

The cursor is base64-JSON encoding ``(start_seq, table, last_id)``.
``start_seq`` is captured on the **first** request (when ``cursor is
None``) and threaded through every subsequent cursor; this is the
correctness pin for events arriving mid-transfer. Returned as
``event_log_cursor`` on the terminal batch — the client uses it to
start ``GET /events`` catch-up (M2.4) and as the M3 WS hello cursor.

Tenant scoping is structural — Layer 1 of ``db._listeners`` injects
``WHERE tenant_id = <ctx>`` on every ORM SELECT, including the
``MAX(event_log.seq)`` and ``MAX(schema_change_log.seq)`` aggregates
via the listener's get-final-froms fallback path.

Batch size: ``cursor`` defaults to ``None``, ``results_per_page``
defaults to ``INITIAL_SYNC_DEFAULT_BATCH_SIZE`` (1000) and is capped at
``INITIAL_SYNC_MAX_BATCH_SIZE`` (5000); both constants live in
``config.py`` and are imported directly by the controller. Bad input
(negative cursor format, out-of-range batch size) renders as
``application/problem+json`` per ADR-016, via Litestar's standard
validation pipeline plus ``PayloadShapeError(INVALID_PAYLOAD_SHAPE)``
for cursor-decode failures.

Implementation lives in ``domain/sync/_pagination.py``
(``InitialSyncPaginator``); the controller's ``initial`` handler is a
thin pass-through. Empty intermediate tables are collapsed
server-side, so an empty tenant returns in a single round-trip.
````

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude-md): document GET /sync/initial bulk transfer endpoint (M2.3)

New subsection describing the InitialSyncBatch envelope, the
table-tagged discriminated body, the opaque cursor and the
start_seq-on-first-request correctness pin, and the connection
to M2.4 catch-up and M3 WS handshake.
EOF
)"
```

---

## Task 23: ADR-015 status flip + final check

**Files:**
- Modify: `docs/adr/015-initial-sync-full-dataset.md`

- [ ] **Step 1: Flip the status**

Edit `docs/adr/015-initial-sync-full-dataset.md`. Change:

```markdown
## Status

Proposed
```

to:

```markdown
## Status

Accepted (2026-05-18)
```

(Per the user's memory on ADR immutability: don't touch the body of an Accepted ADR. Only the Status line gets a date appended on acceptance.)

- [ ] **Step 2: Run `just check`**

Run: `just check`
Expected: lint, format, typecheck, and tests all pass.

If the ruff ratchet has decreased (we may have fixed pre-existing
violations incidentally), run:

```sh
just ratchet-update
```

and amend the staged ratchet baseline into the next commit.

If the ratchet shows new violations, **fix them** rather than bumping
the baseline (user's memory on the ruff ratchet workflow).

- [ ] **Step 3: Commit**

```bash
git add docs/adr/015-initial-sync-full-dataset.md
# If the ratchet was updated:
git add .ruff-ratchet.json 2>/dev/null || true
git commit -m "$(cat <<'EOF'
docs(adr): ADR-015 Accepted (M2.3 shipped)

Initial-sync bulk projection transfer is now implemented behind
GET /sync/initial. Status: Proposed -> Accepted (2026-05-18).
EOF
)"
```

- [ ] **Step 4: Final smoke check**

Run: `uv run pytest tests/sync -v`
Expected: every test in `tests/sync/` PASSes (cursor, pagination, endpoint, isolation).

Run: `just check`
Expected: clean across the board.

Issue #33 closes on merge.

---

## Self-review notes (already applied)

Cross-checked the plan against the spec section-by-section:

- **Settings** — Task 1.
- **Cursor encoding** — Task 3, including the tamper-rejection tests called out in the spec.
- **Row views** — Task 4. Omits ``name`` / ``properties`` as required.
- **Discriminated body union + ``InitialSyncBatch``** — Task 4.
- **Read services** — Task 5; uses the existing ``EventLog``-style pattern.
- **Paginator algorithm** (incl. empty-intermediate collapse, fixed table order, terminal ``event_log_cursor``) — Tasks 6–13.
- **``start_seq`` correctness invariant** — Task 11 explicitly.
- **Controller + ``Parameter(...)`` bounds + DI** — Task 14.
- **``asgi.create_app`` wiring** — Task 14.
- **E2E coverage matrix** — Tasks 15–20: empty tenant, single round-trip with HLC preservation, multi-batch, mid-transfer schema-version advance, bad cursor, bad page-size, tombstone inclusion.
- **Cross-tenant isolation** — Task 21.
- **CLAUDE.md + ADR-015 status flip** — Tasks 22–23.

No placeholders. Every step gives the actual content. Type names used
across tasks are consistent (``InitialSyncTable``, ``CursorState``,
``InitialSyncPaginator``, the four ``*BatchBody`` variants).
