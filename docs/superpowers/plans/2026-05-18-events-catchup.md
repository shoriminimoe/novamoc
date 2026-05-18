# GET /events Catch-up Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `GET /events`, a cursor-paginated HTTP endpoint that returns the active tenant's `event_log` rows after a client-supplied cursor, in `seq` order, in bounded batches. Closes issue #34 (M2.4).

**Architecture:** New read route on the existing `EventsController`. Storage gains a `type_id` column on `event_log` so the response envelope can be reconstructed without joining the projection. The wire shape is a new `RecordedEvent` msgspec struct that M3's WebSocket fan-out will reuse verbatim. Pagination uses Litestar's `CursorPagination[int, RecordedEvent]` via an `AbstractAsyncCursorPaginator` subclass.

**Tech Stack:** Python 3.14, Litestar, msgspec, SQLAlchemy 2 (async), advanced-alchemy, aiosqlite, pytest, uv, ruff, ty.

**Spec:** [`docs/superpowers/specs/2026-05-18-events-catchup-design.md`](../specs/2026-05-18-events-catchup-design.md)

---

## Task 1: Add `type_id` column to `event_log` + write it on append

The wire envelope needs `type_id`; the current `event_log` table doesn't store it. Add the column to the model and start populating it on every event append. Existing endpoint tests are black-box and post valid events (they already carry `type_id` on the envelope), so they keep passing once the bundle writes the new column.

**Files:**
- Modify: `src/py/novamoc/db/models/data/_event.py`
- Modify: `src/py/novamoc/domain/events/_bundle.py:111-140` (`append_event` method)
- Create: `tests/events/test_event_log_type_id.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/events/test_event_log_type_id.py
"""``event_log.type_id`` is populated on every accepted event (spec §Storage)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from novamoc.db.models.data import EventLog
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_append_event_persists_type_id(session: AsyncSession) -> None:
    type_id = uuid4()
    instance_id = uuid4()
    bundle = EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )

    await bundle.append_event(
        EventEnvelope(
            hlc="0001700000000000-00000-abc",
            family=EntityFamily.ASSET,
            type_id=type_id,
            instance_id=instance_id,
            body=Created(values={}),
        )
    )

    result = await session.execute(select(EventLog).limit(1))
    row = result.scalar_one()
    assert row.type_id == str(type_id)
    assert row.entity_id == str(instance_id)
```

- [ ] **Step 2: Run test to verify it fails**

```sh
uv run pytest tests/events/test_event_log_type_id.py -v
```

Expected: FAIL — `AttributeError: 'EventLog' object has no attribute 'type_id'` (or the test fails at row construction time because the model lacks the column).

- [ ] **Step 3: Add the column to the model**

Edit `src/py/novamoc/db/models/data/_event.py`. Add `type_id` between `table_name` and `entity_id`:

```python
class EventLog(DefaultBase):
    """Append-only data event log (ADR-002, ADR-011).

    Source of truth for all synchronized data. ``seq`` is globally monotonic;
    per-tenant streaming uses ``(tenant_id, seq)``. ``UNIQUE(tenant_id, hlc)``
    enforces idempotent re-delivery. Not derived from ``BigIntAuditBase``
    because ADR-011 mandates the column be named ``seq``, not ``id``;
    ``received_at`` serves the audit role for an append-only log.
    """

    __tablename__ = "event_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "hlc", name="uq_event_log_tenant_hlc"),
        Index("idx_event_log_tenant_seq", "tenant_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(
        BigIntIdentity, primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[str]
    hlc: Mapped[str]
    schema_version: Mapped[int] = mapped_column(BigInteger)
    table_name: Mapped[str]
    type_id: Mapped[str]
    entity_id: Mapped[str]
    field_id: Mapped[str | None]
    op: Mapped[EventOp] = mapped_column(Enum(EventOp, native_enum=False))
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    received_at: Mapped[datetime] = mapped_column(
        DateTimeUTC, server_default=func.now()
    )
```

- [ ] **Step 4: Pass `type_id` on append**

Edit `src/py/novamoc/domain/events/_bundle.py`. In `EventServiceBundle.append_event`, add `type_id` to the `data=` dict:

```python
await self.event_log_service.create(
    data={
        "hlc": event.hlc,
        "schema_version": self.schema_version,
        "table_name": _TABLE_NAMES[event.family],
        "type_id": str(event.type_id),
        "entity_id": str(event.instance_id),
        "field_id": None,
        "op": _op_for_body(event.body),
        "value_json": _value_json_for_body(event.body),
    },
    auto_commit=False,
)
```

- [ ] **Step 5: Run the new test + the full event suite to confirm nothing regressed**

```sh
uv run pytest tests/events/test_event_log_type_id.py -v
uv run pytest tests/events/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```sh
git add src/py/novamoc/db/models/data/_event.py \
        src/py/novamoc/domain/events/_bundle.py \
        tests/events/test_event_log_type_id.py
git commit -m "feat(events): store type_id on event_log rows (M2.4)"
```

---

## Task 2: Add `RecordedEvent` wire struct

This is the read-side counterpart to `EventEnvelope`. Pure msgspec struct definition — value comes from later tasks that emit it. A round-trip encode/decode test pins the shape.

**Files:**
- Modify: `src/py/novamoc/domain/events/_payloads.py` (append `RecordedEvent` after the existing structs)
- Create: `tests/events/test_recorded_event.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/events/test_recorded_event.py
"""``RecordedEvent`` round-trips encode → decode unchanged."""

from __future__ import annotations

import datetime as _dt
from uuid import uuid4

import msgspec

from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    RecordedEvent,
)


def test_recorded_event_encode_decode_round_trip() -> None:
    original = RecordedEvent(
        seq=42,
        schema_version=7,
        hlc="0001700000000000-00000-abc",
        family=EntityFamily.ASSET,
        type_id=uuid4(),
        instance_id=uuid4(),
        body=Created(values={"col:name": "Truck-1"}),
        received_at=_dt.datetime(2026, 5, 18, 12, 0, tzinfo=_dt.UTC),
    )
    wire = msgspec.json.encode(original)
    round_tripped = msgspec.json.decode(wire, type=RecordedEvent)
    assert round_tripped == original
```

- [ ] **Step 2: Run test to verify it fails**

```sh
uv run pytest tests/events/test_recorded_event.py -v
```

Expected: FAIL — `ImportError: cannot import name 'RecordedEvent'`.

- [ ] **Step 3: Add the struct**

Append to `src/py/novamoc/domain/events/_payloads.py`:

```python
class RecordedEvent(msgspec.Struct, forbid_unknown_fields=True):
    """Server-recorded event, as emitted on read transports.

    The read-side twin of :class:`EventEnvelope`. Adds the server-
    assigned fields (``seq``, ``schema_version``, ``received_at``) the
    write-side envelope lacks. Body shape is shared with
    :class:`EventEnvelope`, so clients pattern-match the same way
    regardless of direction.

    Attributes:
        seq: Replication cursor (ADR-011).
        schema_version: Acceptance-time schema version. Drives client-
            side gating per ADR-013 / ADR-009.
        hlc: LWW key, identical to :attr:`EventEnvelope.hlc`.
        family: Meta-schema family.
        type_id: User-schema type FK.
        instance_id: User-data instance id.
        body: Discriminated event payload — same union as
            :class:`EventEnvelope`.
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

Imports to add at the top of `_payloads.py` (if not already present):

```python
from datetime import datetime
```

- [ ] **Step 4: Run test to verify it passes**

```sh
uv run pytest tests/events/test_recorded_event.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/_payloads.py \
        tests/events/test_recorded_event.py
git commit -m "feat(events): add RecordedEvent read-side wire struct (M2.4)"
```

---

## Task 3: Body reconstruction helper + family inverse map

Reverse of `_value_json_for_body` / `_op_for_body` so we can rebuild an `EventBody` from an `EventLog` row, plus the inverse of `_TABLE_NAMES` so we can recover `EntityFamily` from `table_name`. Both live in `_bundle.py` next to their forward direction so the round-trip is one file.

**Files:**
- Modify: `src/py/novamoc/domain/events/_bundle.py` (add `_FAMILY_BY_TABLE_NAME` and `body_from_row`)
- Modify: `tests/events/test_recorded_event.py` (add body-reconstruction cases)

- [ ] **Step 1: Write the failing tests**

Append to `tests/events/test_recorded_event.py`:

```python
import pytest

from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events._bundle import _FAMILY_BY_TABLE_NAME, body_from_row
from novamoc.domain.events._payloads import (
    Activated,
    Deactivated,
    Updated,
)


def _row(op: EventOp, value_json) -> EventLog:
    return EventLog(
        seq=1,
        tenant_id="t",
        hlc="0001700000000000-00000-abc",
        schema_version=0,
        table_name="assets",
        type_id=str(uuid4()),
        entity_id=str(uuid4()),
        field_id=None,
        op=op,
        value_json=value_json,
        received_at=_dt.datetime(2026, 5, 18, 12, 0, tzinfo=_dt.UTC),
    )


def test_body_from_row_created() -> None:
    row = _row(EventOp.SET, {"event": "created", "values": {"col:name": "T-1"}})
    assert body_from_row(row) == Created(values={"col:name": "T-1"})


def test_body_from_row_updated() -> None:
    row = _row(EventOp.SET, {"event": "updated", "values": {"col:name": "T-2"}})
    assert body_from_row(row) == Updated(values={"col:name": "T-2"})


def test_body_from_row_activated() -> None:
    row = _row(EventOp.SET, {"event": "activated"})
    assert body_from_row(row) == Activated()


def test_body_from_row_deactivated_uses_op_not_value_json() -> None:
    row = _row(EventOp.DELETE, None)
    assert body_from_row(row) == Deactivated()


@pytest.mark.parametrize(
    ("table_name", "family"),
    [
        ("assets", EntityFamily.ASSET),
        ("maintenance_records", EntityFamily.MAINTENANCE_RECORD),
    ],
)
def test_family_by_table_name_inverse_of_table_names(
    table_name: str, family: EntityFamily
) -> None:
    assert _FAMILY_BY_TABLE_NAME[table_name] is family
```

- [ ] **Step 2: Run tests to verify they fail**

```sh
uv run pytest tests/events/test_recorded_event.py -v
```

Expected: FAIL — `ImportError: cannot import name '_FAMILY_BY_TABLE_NAME'` / `body_from_row`.

- [ ] **Step 3: Add the helpers to `_bundle.py`**

In `src/py/novamoc/domain/events/_bundle.py`, after the existing `_TABLE_NAMES` constant, add:

```python
_FAMILY_BY_TABLE_NAME: Final[dict[str, EntityFamily]] = {
    name: family for family, name in _TABLE_NAMES.items()
}


def body_from_row(row: EventLog) -> EventBody:
    """Reverse of :func:`_value_json_for_body` / :func:`_op_for_body`.

    A ``DELETE``-op row reconstructs to :class:`Deactivated`; every
    other row's ``value_json`` carries the tagged dict
    :func:`msgspec.to_builtins` wrote, so :func:`msgspec.convert`
    against the :data:`EventBody` union picks the right variant via
    the ``event`` discriminator tag (ADR-011 §"Schema: ``value_json
    TEXT, -- NULL for deletes``").
    """
    if row.op is EventOp.DELETE:
        return Deactivated()
    return msgspec.convert(row.value_json, type=EventBody)
```

Update the imports in `_bundle.py` if needed:

```python
from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events._payloads import (
    Created,
    Deactivated,
    EntityFamily,
    EventBody,
    EventOutcome,
    Updated,
)
```

(`EventBody` and `EventLog` may already be imported; if not, add them under `TYPE_CHECKING` if only used in annotations, but `body_from_row` calls `msgspec.convert(..., type=EventBody)` at runtime so `EventBody` must be a runtime import.)

- [ ] **Step 4: Run tests to verify they pass**

```sh
uv run pytest tests/events/test_recorded_event.py -v
```

Expected: PASS for all 5 new tests + the round-trip from Task 2.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/_bundle.py \
        tests/events/test_recorded_event.py
git commit -m "feat(events): body_from_row + family inverse map (M2.4)"
```

---

## Task 4: Add `event_catchup_*` settings knobs

Two new dataclass fields on `AppSettings`, with env-var defaults using the project's existing `_*_env` helpers. A new `_int_env` helper is needed because nothing else in the file parses ints from env. Test-mirrors the existing `test_config.py` style.

**Files:**
- Modify: `src/py/novamoc/config.py` (add `_int_env` helper + two `AppSettings` fields)
- Modify: `tests/test_config.py` (add `TestIntEnv` + tests for the two new fields)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from novamoc.config import _int_env  # add to the imports list at the top


class TestIntEnv:
    def test_returns_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_INT", raising=False)
        assert _int_env("NOVAMOC_X_TEST_INT", 7)() == 7

    def test_parses_env_value_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_INT", "42")
        assert _int_env("NOVAMOC_X_TEST_INT", 7)() == 42

    def test_garbage_propagates_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_INT", "not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            _int_env("NOVAMOC_X_TEST_INT", 7)()


class TestAppEventCatchupSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "NOVAMOC_EVENT_CATCHUP_DEFAULT_BATCH_SIZE",
            "NOVAMOC_EVENT_CATCHUP_MAX_BATCH_SIZE",
        ):
            monkeypatch.delenv(name, raising=False)
        app = AppSettings()
        assert app.event_catchup_default_batch_size == 500
        assert app.event_catchup_max_batch_size == 5000

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_EVENT_CATCHUP_DEFAULT_BATCH_SIZE", "100")
        monkeypatch.setenv("NOVAMOC_EVENT_CATCHUP_MAX_BATCH_SIZE", "1000")
        app = AppSettings()
        assert app.event_catchup_default_batch_size == 100
        assert app.event_catchup_max_batch_size == 1000
```

- [ ] **Step 2: Run tests to verify they fail**

```sh
uv run pytest tests/test_config.py::TestIntEnv tests/test_config.py::TestAppEventCatchupSettings -v
```

Expected: FAIL — `ImportError: cannot import name '_int_env'` and the AppSettings tests fail with `AttributeError`.

- [ ] **Step 3: Add `_int_env` helper to `config.py`**

In `src/py/novamoc/config.py`, after `_float_env`:

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

- [ ] **Step 4: Add the two fields to `AppSettings`**

In `src/py/novamoc/config.py`, extend `AppSettings`:

```python
@dataclass(frozen=True, slots=True)
class AppSettings:
    """App-wide tunables that don't belong to a single subsystem.

    Attributes:
        docs_base_url: Base URL the problem-details ``type`` URIs
            point at (the static-files router under ``/problems``
            is served from the same host).
        hlc_drift_limit_seconds: One-sided clock-drift budget
            (ADR-006). Events whose HLC physical component sits
            more than this many seconds ahead of the server wall
            clock are rejected at acceptance time.
        event_catchup_default_batch_size: Default ``results_per_page``
            for ``GET /events`` when the client omits the query
            parameter (M2.4).
        event_catchup_max_batch_size: Hard upper bound on
            ``results_per_page`` for ``GET /events``. Requests above
            this fail validation at 400.
    """

    docs_base_url: str = field(
        default_factory=_str_env(
            "NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://localhost:8000"
        )
    )
    hlc_drift_limit_seconds: float = field(
        default_factory=_float_env("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", 60.0)
    )
    event_catchup_default_batch_size: int = field(
        default_factory=_int_env(
            "NOVAMOC_EVENT_CATCHUP_DEFAULT_BATCH_SIZE", 500
        )
    )
    event_catchup_max_batch_size: int = field(
        default_factory=_int_env(
            "NOVAMOC_EVENT_CATCHUP_MAX_BATCH_SIZE", 5000
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```sh
uv run pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```sh
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): event_catchup_* batch-size settings (M2.4)"
```

---

## Task 5: `EventLogCursorPaginator`

The cursor-paginated reader. Driven by `AbstractAsyncCursorPaginator[int, RecordedEvent]`. Internally fetches `results_per_page + 1` rows and uses the overflow to compute `next_cursor` without a separate `COUNT`. Tenant scoping is structural — Layer 1 listeners inject the predicate.

**Files:**
- Create: `src/py/novamoc/domain/events/_pagination.py`
- Create: `tests/events/test_pagination.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/events/test_pagination.py
"""``EventLogCursorPaginator`` unit tests against in-memory SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._pagination import EventLogCursorPaginator
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
    RecordedEvent,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _append_n(bundle: EventServiceBundle, n: int) -> None:
    """Append N Created events for the active tenant."""
    type_id = uuid4()
    for i in range(n):
        await bundle.append_event(
            EventEnvelope(
                hlc=f"00017000000000{i:02d}-00000-abc",
                family=EntityFamily.ASSET,
                type_id=type_id,
                instance_id=uuid4(),
                body=Created(values={}),
            )
        )


@pytest.fixture
def paginator(session: AsyncSession) -> EventLogCursorPaginator:
    return EventLogCursorPaginator(EventLogService(session=session))


@pytest.fixture
def bundle(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )


async def test_get_items_empty_stream_returns_no_items_and_no_cursor(
    paginator: EventLogCursorPaginator,
) -> None:
    items, cursor = await paginator.get_items(cursor=None, results_per_page=10)
    assert items == []
    assert cursor is None


async def test_get_items_returns_all_when_under_page_size(
    paginator: EventLogCursorPaginator, bundle: EventServiceBundle
) -> None:
    await _append_n(bundle, 3)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=10)
    assert len(items) == 3
    assert all(isinstance(it, RecordedEvent) for it in items)
    assert [it.seq for it in items] == sorted(it.seq for it in items)
    assert cursor is None  # caught up


async def test_get_items_returns_first_page_and_signals_more(
    paginator: EventLogCursorPaginator, bundle: EventServiceBundle
) -> None:
    await _append_n(bundle, 5)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=2)
    assert len(items) == 2
    assert cursor == items[-1].seq


async def test_get_items_cursor_handoff_continues_stream(
    paginator: EventLogCursorPaginator, bundle: EventServiceBundle
) -> None:
    await _append_n(bundle, 5)
    page1, cursor1 = await paginator.get_items(cursor=None, results_per_page=2)
    page2, cursor2 = await paginator.get_items(cursor=cursor1, results_per_page=2)
    page3, cursor3 = await paginator.get_items(cursor=cursor2, results_per_page=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    assert cursor3 is None  # caught up

    all_seqs = [it.seq for it in page1 + page2 + page3]
    assert all_seqs == sorted(all_seqs)
    assert len(set(all_seqs)) == 5  # no duplicates


async def test_get_items_exact_page_boundary_signals_caught_up(
    paginator: EventLogCursorPaginator, bundle: EventServiceBundle
) -> None:
    await _append_n(bundle, 4)
    items, cursor = await paginator.get_items(cursor=None, results_per_page=4)
    assert len(items) == 4
    assert cursor is None  # the +1 fetch returned only 4, so we're done
```

- [ ] **Step 2: Run tests to verify they fail**

```sh
uv run pytest tests/events/test_pagination.py -v
```

Expected: FAIL — `ImportError: cannot import name 'EventLogCursorPaginator'`.

- [ ] **Step 3: Create the paginator module**

`src/py/novamoc/domain/events/_pagination.py`:

```python
"""Cursor-paginated reader over ``event_log`` for the active tenant.

The HTTP catch-up endpoint (M2.4, ADR-013 §"HTTP `/sync`") streams
recorded events to a returning client. The M3 WebSocket fan-out emits
the same :class:`RecordedEvent` envelope so the wire format is
identical regardless of transport.

Tenant scoping is structural: Layer 1 of :mod:`db._listeners` injects
``WHERE tenant_id = <ctx>`` on every ORM SELECT against ``event_log``,
so the paginator carries no tenant predicate of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.filters import LimitOffset, OrderBy
from litestar.pagination import AbstractAsyncCursorPaginator
from sqlalchemy import ColumnElement

from novamoc.db.models.data import EventLog
from novamoc.domain.events._bundle import _FAMILY_BY_TABLE_NAME, body_from_row
from novamoc.domain.events._payloads import RecordedEvent

if TYPE_CHECKING:
    from novamoc.domain.events.services import EventLogService


def _row_to_recorded_event(row: EventLog) -> RecordedEvent:
    """Project an ``event_log`` row into the :class:`RecordedEvent` wire
    shape."""
    return RecordedEvent(
        seq=row.seq,
        schema_version=row.schema_version,
        hlc=row.hlc,
        family=_FAMILY_BY_TABLE_NAME[row.table_name],
        type_id=UUID(row.type_id),
        instance_id=UUID(row.entity_id),
        body=body_from_row(row),
        received_at=row.received_at,
    )


class EventLogCursorPaginator(AbstractAsyncCursorPaginator[int, RecordedEvent]):
    """Cursor pagination over ``event_log`` rows for the active tenant.

    Cursor semantics:

    * ``cursor=None`` — start from the beginning of the tenant's stream.
    * ``cursor=N`` — return rows with ``seq > N`` (exclusive, ADR-011).
    * Returned cursor is the ``seq`` of the last row when more rows
      remain, or ``None`` when the caller has reached the end.

    Implementation fetches ``results_per_page + 1`` to detect overflow
    without a separate ``COUNT``.
    """

    def __init__(self, event_log_service: EventLogService) -> None:
        self._service = event_log_service

    async def get_items(
        self, cursor: int | None, results_per_page: int
    ) -> tuple[list[RecordedEvent], int | None]:
        statement_filter: ColumnElement[bool] | None = (
            EventLog.seq > cursor if cursor is not None else None
        )
        list_args: tuple = (
            OrderBy(field_name="seq"),
            LimitOffset(limit=results_per_page + 1, offset=0),
        )
        if statement_filter is not None:
            rows = await self._service.list(statement_filter, *list_args)
        else:
            rows = await self._service.list(*list_args)

        has_more = len(rows) > results_per_page
        page = rows[:results_per_page]
        items = [_row_to_recorded_event(row) for row in page]
        next_cursor = page[-1].seq if has_more else None
        return items, next_cursor
```

> **Note.** advanced-alchemy's `.list()` accepts both `StatementFilter` objects and SQLAlchemy `ColumnElement` predicates positionally. The `EventLog.seq > cursor` predicate is the latter. If ty or ruff complains about the heterogeneous tuple, narrow the `list_args` build to two separate `await self._service.list(...)` call sites (one with the filter, one without) — both branches already exist in the snippet above.

- [ ] **Step 4: Run tests to verify they pass**

```sh
uv run pytest tests/events/test_pagination.py -v
```

Expected: PASS for all 5 tests.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/_pagination.py \
        tests/events/test_pagination.py
git commit -m "feat(events): EventLogCursorPaginator (M2.4)"
```

---

## Task 6: Wire `GET /events` on `EventsController`

Add the read handler, the DI provider that hands the paginator into it, and the assertion that Settings literals match the `Parameter(le=...)` annotation. One thin E2E test pins the happy path; pagination/validation tests come in Task 7.

**Files:**
- Modify: `src/py/novamoc/domain/events/controllers/_events.py`
- Create: `tests/events/test_endpoint_catchup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/events/test_endpoint_catchup.py
"""``GET /events`` catch-up endpoint (M2.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_get_events_empty_stream_returns_no_items(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["cursor"] is None
    assert body["results_per_page"] == 500


async def test_get_events_returns_appended_events(
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

    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    event = body["items"][0]
    assert event["hlc"] == "0001700000000000-00000-abc"
    assert event["family"] == "asset"
    assert event["type_id"] == type_id
    assert event["instance_id"] == instance_id
    assert event["body"] == {
        "event": "created",
        "values": {"col:name": "Truck-1"},
    }
    assert event["seq"] > 0
    assert event["schema_version"] == 0
    assert "received_at" in event
    assert body["cursor"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```sh
uv run pytest tests/events/test_endpoint_catchup.py -v
```

Expected: FAIL — 404 on `GET /events/` (no handler yet).

- [ ] **Step 3: Add the handler and DI wiring**

Edit `src/py/novamoc/domain/events/controllers/_events.py`. Add a paginator provider, an import-time bounds assertion, and the `@get("/")` handler.

Imports (add to the existing import block):

```python
from typing import Annotated

from litestar import get
from litestar.pagination import CursorPagination
from litestar.params import Parameter

from novamoc.config import AppSettings
from novamoc.domain.events._pagination import EventLogCursorPaginator
from novamoc.domain.events._payloads import RecordedEvent
```

Add the import-time assertion below the imports (catches future Settings drift):

```python
# The ``Annotated[..., Parameter(le=...)]`` form requires a literal bound
# at function-definition time. We mirror :class:`AppSettings`'
# ``event_catchup_max_batch_size`` here; an assertion locks the values
# together so a settings change without a code change fails at import.
_DEFAULT_BATCH_SIZE = 500
_MAX_BATCH_SIZE = 5000
assert AppSettings.__dataclass_fields__[  # noqa: S101  # import-time invariant
    "event_catchup_default_batch_size"
].default_factory() == _DEFAULT_BATCH_SIZE
assert AppSettings.__dataclass_fields__[  # noqa: S101  # import-time invariant
    "event_catchup_max_batch_size"
].default_factory() == _MAX_BATCH_SIZE
```

(If the field's `default_factory` reads env, the assertion still works in a clean test env. If the env is set to a non-default value at import time, the assertion fails and the developer is forced to align the literal with their override or pick a different mechanism. That's the intended friction.)

Add the paginator DI provider:

```python
async def _provide_event_log_cursor_paginator(
    event_log_service: EventLogService,
) -> EventLogCursorPaginator:
    return EventLogCursorPaginator(event_log_service)
```

Wire it into `dependencies` on `EventsController`:

```python
dependencies = (
    {
        "drift_limit_seconds": Provide(_provide_drift_limit_seconds),
        "docs_base_url": Provide(_provide_docs_base_url),
        "deps": Provide(_provide_append_deps),
        "event_log_cursor_paginator": Provide(
            _provide_event_log_cursor_paginator
        ),
    }
    | providers.create_service_dependencies(
        SchemaChangeLogService, "schema_change_log_service"
    )
    | providers.create_service_dependencies(
        AssetTypeFieldService, "asset_type_field_service"
    )
    | providers.create_service_dependencies(
        MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service"
    )
    | providers.create_service_dependencies(EventLogService, "event_log_service")
)
```

Add the handler on `EventsController`:

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
    event_log_cursor_paginator: EventLogCursorPaginator,
    cursor: Annotated[int | None, Parameter(ge=0)] = None,
    results_per_page: Annotated[
        int, Parameter(ge=1, le=_MAX_BATCH_SIZE)
    ] = _DEFAULT_BATCH_SIZE,
) -> CursorPagination[int, RecordedEvent]:
    return await event_log_cursor_paginator(
        cursor=cursor, results_per_page=results_per_page
    )
```

You'll also need `from novamoc.api._problem_details import ProblemDetails` (existing import on the schema controller; mirror it) and `from litestar.openapi.datastructures import ResponseSpec`. Check the existing schema controller for the exact import names if either is missing.

- [ ] **Step 4: Run tests to verify they pass**

```sh
uv run pytest tests/events/test_endpoint_catchup.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

```sh
uv run pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```sh
git add src/py/novamoc/domain/events/controllers/_events.py \
        tests/events/test_endpoint_catchup.py
git commit -m "feat(events): GET /events catch-up endpoint (M2.4)"
```

---

## Task 7: Endpoint test coverage — pagination, body round-trip, schema_version, validation

The Task 6 happy-path test confirmed the wiring. This task fills in the rest: cursor handoff over HTTP, every body variant round-trips, `schema_version` is preserved across a schema change, and bad input goes to 400 ProblemDetails. No new code — just tests against the existing handler.

**Files:**
- Modify: `tests/events/test_endpoint_catchup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/events/test_endpoint_catchup.py`:

```python
async def test_get_events_paginates_via_cursor(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())

    async def post_one(i: int) -> None:
        hlc = f"00017000000000{i:02d}-00000-abc"
        resp = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": hlc,
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": str(uuid4()),
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert resp.status_code == 202, resp.text

    for i in range(5):
        await post_one(i)

    resp1 = await client.get("/events/?results_per_page=2")
    body1 = resp1.json()
    assert len(body1["items"]) == 2
    assert body1["cursor"] is not None

    resp2 = await client.get(f"/events/?cursor={body1['cursor']}&results_per_page=2")
    body2 = resp2.json()
    assert len(body2["items"]) == 2
    assert body2["cursor"] is not None

    resp3 = await client.get(f"/events/?cursor={body2['cursor']}&results_per_page=2")
    body3 = resp3.json()
    assert len(body3["items"]) == 1
    assert body3["cursor"] is None

    all_seqs = [it["seq"] for it in body1["items"] + body2["items"] + body3["items"]]
    assert all_seqs == sorted(all_seqs)
    assert len(set(all_seqs)) == 5


async def test_get_events_body_round_trip_all_variants(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())

    posts = [
        {
            "hlc": "0001700000000001-00000-abc",
            "body": {"event": "created", "values": {"col:name": "X"}},
        },
        {
            "hlc": "0001700000000002-00000-abc",
            "body": {"event": "updated", "values": {"col:name": "Y"}},
        },
        {
            "hlc": "0001700000000003-00000-abc",
            "body": {"event": "deactivated"},
        },
        {
            "hlc": "0001700000000004-00000-abc",
            "body": {"event": "activated"},
        },
    ]
    for p in posts:
        resp = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": p["hlc"],
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": instance_id,
                        "body": p["body"],
                    }
                ],
            },
        )
        assert resp.status_code == 202, resp.text

    resp = await client.get("/events/")
    items = resp.json()["items"]
    assert len(items) == 4
    by_hlc = {it["hlc"]: it for it in items}
    for p in posts:
        assert by_hlc[p["hlc"]]["body"] == p["body"]


async def test_get_events_preserves_acceptance_time_schema_version(
    client: AsyncTestClient,
) -> None:
    # Post a Created event at schema_version=0.
    type_id = str(uuid4())
    post1 = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000001-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": str(uuid4()),
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert post1.status_code == 202, post1.text

    # Advance the schema (create_asset_type) → schema_version becomes 1.
    schema_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "definition": {"name": "Truck"},
        },
    )
    assert schema_resp.status_code == 200, schema_resp.text

    # The recorded event still carries the version it was accepted under.
    resp = await client.get("/events/")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["schema_version"] == 0


async def test_get_events_rejects_negative_cursor(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?cursor=-1")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_get_events_rejects_zero_results_per_page(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?results_per_page=0")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_get_events_rejects_oversized_results_per_page(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?results_per_page=5001")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
```

- [ ] **Step 2: Run tests to verify all pass**

```sh
uv run pytest tests/events/test_endpoint_catchup.py -v
```

Expected: PASS for all six new tests + the two from Task 6.

> **If** the `test_get_events_preserves_acceptance_time_schema_version` test fails with a `schema_version_stale` rejection from `POST /schema`, the schema endpoint's command-payload shape may be a tagged discriminated union that wants `{"type": "create_asset_type", ...}` differently. Check `tests/schema/test_endpoint_e2e.py::test_post_schema_creates_asset_type` for the exact body shape and adapt the test.

- [ ] **Step 3: Commit**

```sh
git add tests/events/test_endpoint_catchup.py
git commit -m "test(events): catch-up endpoint pagination + validation (M2.4)"
```

---

## Task 8: Cross-tenant isolation test

Mirrors `tests/schema/test_cross_tenant_isolation.py`. Seeds events for `t-a` and `t-b` interleaved at adjacent `seq` values; under each tenant context, asserts the catch-up sees only its own events.

**Files:**
- Create: `tests/events/test_catchup_cross_tenant_isolation.py`

- [ ] **Step 1: Sanity-check the existing pattern**

Read `tests/schema/test_cross_tenant_isolation.py` to confirm the tenant-fixture parametrisation style and the `use_tenant` helper usage. The events isolation test mirrors that shape.

```sh
ls tests/schema/test_cross_tenant_isolation.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/events/test_catchup_cross_tenant_isolation.py
"""``EventLogCursorPaginator`` returns only the active tenant's events."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from novamoc.db._tenant_context import use_tenant
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._pagination import EventLogCursorPaginator
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = []  # explicit empty — see ``no_tenant`` marker below


def _bundle(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )


async def _append(bundle: EventServiceBundle, hlc: str) -> None:
    await bundle.append_event(
        EventEnvelope(
            hlc=hlc,
            family=EntityFamily.ASSET,
            type_id=uuid4(),
            instance_id=uuid4(),
            body=Created(values={}),
        )
    )


async def test_paginator_isolates_tenants_at_interleaved_seqs(
    session: AsyncSession,
) -> None:
    bundle = _bundle(session)

    # Interleave: t-a, t-b, t-a, t-b, t-a → three events for t-a, two for t-b.
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000001-00000-aaa")
    with use_tenant("t-b"):
        await _append(bundle, "0001700000000002-00000-bbb")
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000003-00000-aaa")
    with use_tenant("t-b"):
        await _append(bundle, "0001700000000004-00000-bbb")
    with use_tenant("t-a"):
        await _append(bundle, "0001700000000005-00000-aaa")

    paginator = EventLogCursorPaginator(EventLogService(session=session))

    with use_tenant("t-a"):
        items_a, cursor_a = await paginator.get_items(
            cursor=None, results_per_page=100
        )
    with use_tenant("t-b"):
        items_b, cursor_b = await paginator.get_items(
            cursor=None, results_per_page=100
        )

    assert {it.hlc for it in items_a} == {
        "0001700000000001-00000-aaa",
        "0001700000000003-00000-aaa",
        "0001700000000005-00000-aaa",
    }
    assert {it.hlc for it in items_b} == {
        "0001700000000002-00000-bbb",
        "0001700000000004-00000-bbb",
    }
    assert cursor_a is None
    assert cursor_b is None
```

> **Note on the `tenant` fixture.** The project's `tests/conftest.py` autouses a `tenant` fixture that sets `current_tenant_id` to `"t1"` for the duration of each test. This test reads through that contextvar via `use_tenant("t-a")` / `use_tenant("t-b")` context managers — they push/pop the contextvar over the autouse default, so the test does its own scoping inside the function body.

- [ ] **Step 3: Run the test to verify it fails (or passes)**

```sh
uv run pytest tests/events/test_catchup_cross_tenant_isolation.py -v
```

Expected: PASS already, since the tenant scoping is structural (Layer 1 of `db._listeners` injects the predicate). The test is a regression guard — if it fails, the listener wiring has broken and that's a P0 production bug, not a test bug.

- [ ] **Step 4: Commit**

```sh
git add tests/events/test_catchup_cross_tenant_isolation.py
git commit -m "test(events): cross-tenant isolation for catch-up (M2.4)"
```

---

## Task 9: Update CLAUDE.md

Add a brief subsection on `GET /events` to the existing "Events endpoint" section so future readers find the read-path documentation alongside the write-path documentation.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Edit `CLAUDE.md`**

Find the "Events endpoint (`POST /events`)" section. Immediately after that section's closing paragraph (before the next top-level section), add:

```markdown
## Events catch-up endpoint (`GET /events`)

Counterpart to `POST /events` and the HTTP half of the catch-up flow
(ADR-013). Returns the active tenant's ``event_log`` rows after a
client-supplied cursor in ``seq`` order, in bounded batches.

Response shape is Litestar's ``CursorPagination[int, RecordedEvent]``
(``domain/events/_payloads.py``): ``items`` plus a ``cursor`` field
that echoes back into the next request's ``?cursor=`` query parameter,
or ``None`` when the caller has reached the end. Cursor semantics are
exclusive (``seq > cursor``, ADR-011). The `RecordedEvent` envelope
adds the server-assigned fields (``seq``, ``schema_version``,
``received_at``) that the write-side ``EventEnvelope`` lacks; the
``body`` is the same discriminated union as on the POST. The M3
WebSocket fan-out emits the same struct so the wire format is
transport-independent (ADR-013).

`event_log.type_id` is populated on every accepted event so the read
side can reconstruct the envelope without joining the projection.

Batch size is bounded by ``Settings.app.event_catchup_max_batch_size``
(default 5000); the default ``results_per_page`` when the client omits
the parameter is ``event_catchup_default_batch_size`` (default 500).
Bad input (negative cursor, out-of-range batch size) renders as
``application/problem+json`` per ADR-016, via Litestar's standard
validation pipeline — no new error codes.

Implementation lives in ``domain/events/_pagination.py``
(``EventLogCursorPaginator``); the controller method
``EventsController.read_stream`` is a thin pass-through.
```

- [ ] **Step 2: Commit**

```sh
git add CLAUDE.md
git commit -m "docs(claude-md): document GET /events catch-up endpoint (M2.4)"
```

---

## Task 10: Final verification

Run the whole pipeline (`lint + format-check + typecheck + tests`) one more time to confirm the branch is releaseable. Push, mark the PR ready for review.

- [ ] **Step 1: Run `just check`**

```sh
just check
```

Expected: all four composite recipes green.

- [ ] **Step 2: Run `just ratchet`**

```sh
just ratchet
```

Expected: no rule's count exceeds its baseline. If any count *dropped*, run `just ratchet-update` and add the resulting `.ruff-ratchet.json` change to a new commit. If a count *rose*, treat as a regression: read `uv run ruff rule <code>`, fix or scope-ignore per CLAUDE.md guidance, and try again.

- [ ] **Step 3: Push**

```sh
git push
```

- [ ] **Step 4: Mark PR ready for review**

```sh
gh pr ready 98
```

(If a separate PR is preferred for the implementation, open it now with `gh pr create` — the existing PR #98 is the spec-only draft. Decide based on your team's review preference; default to a fresh PR so the spec review and the code review stay separable.)

- [ ] **Step 5: Update the GitHub issue**

```sh
gh issue comment 34 --body "Implemented in PR <#nnn>. Closes M2.4."
```

---

## Self-review notes

After writing the plan, I re-checked it against the spec:

* **Spec §Architecture / Storage change** → Task 1 (column + write path).
* **Spec §Architecture / Wire envelope** → Task 2 (struct) + Task 3 (helpers).
* **Spec §Architecture / Cursor pagination** → Task 5 (paginator).
* **Spec §Architecture / Controller** → Task 6 (route + DI).
* **Spec §Architecture / Settings** → Task 4.
* **Spec §Architecture / Error mapping** → exercised in Task 7 (3 negative cases).
* **Spec §Tests / New unit tests** → Tasks 2, 3, 5.
* **Spec §Tests / New endpoint tests** → Tasks 6, 7.
* **Spec §Tests / Cross-tenant isolation** → Task 8.
* **Spec §Migration / CLAUDE.md** → Task 9.

No placeholders, no "implement later", no references to undefined helpers. The only deferred decision is the advanced-alchemy filter syntax for `EventLog.seq > cursor` (Task 5 step 3 names two acceptable spellings). All other code blocks contain the exact content the engineer should commit.
