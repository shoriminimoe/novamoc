# Events handler dispatch — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape PR #64 so the events controller does envelope gates only and per-`(family, body_type)` handlers own field/value validation, with field-set lookups cached per request on the service bundle.

**Architecture:** Add `_bundle.py`, `_dispatch.py`, and `_handlers/{asset,maintenance_record}.py` mirroring the schema endpoint's pattern. Shrink `_validators.py` to a synchronous `validate_values(event, values, fields_by_id)` plus two pure predicates. Slim `controllers/_events.py` to: schema-version gate → per-event HLC parse + drift check → `dispatch(services, auth, event)`.

**Tech Stack:** Python 3.14, msgspec for wire shapes, advanced-alchemy services, Litestar controller/DI, pytest with real in-memory aiosqlite.

**Starting state:** This plan assumes the executor is on PR #64's branch (the branch this plan reshapes). All M1.4 code from PR #64 — `_validators.py`, the controller import of `validate_event_values`, the two new error types, the two new problem-docs, the 12 e2e tests, the 8 predicate unit tests — is already present. The plan reshapes that code; it does not re-do M1.4 from scratch.

**Spec reference:** `docs/superpowers/specs/2026-05-11-events-handler-dispatch-design.md`.

---

## File map

**Created**
- `src/py/novamoc/domain/events/_bundle.py` — `EventServiceBundle` (frozen dataclass) with per-request `fields_for` memo.
- `src/py/novamoc/domain/events/_dispatch.py` — `_HANDLERS` table + `dispatch(services, auth, event)`.
- `src/py/novamoc/domain/events/_handlers/__init__.py` — empty package init.
- `src/py/novamoc/domain/events/_handlers/asset.py` — four handler functions for the asset family.
- `src/py/novamoc/domain/events/_handlers/maintenance_record.py` — four handler functions for the maintenance-record family.
- `tests/events/test_bundle.py` — memoization assertions for `EventServiceBundle.fields_for`.
- `tests/events/test_dispatch.py` — coverage assertion for `_HANDLERS`.
- `tests/events/test_handlers_asset.py` — handler-level integration tests for asset handlers.
- `tests/events/test_handlers_maintenance_record.py` — same for maintenance-record handlers.

**Modified**
- `src/py/novamoc/domain/events/_validators.py` — collapse per-key async helpers into one sync `validate_values`; promote the two public predicates (`json_type_name`, `matches_data_type`).
- `src/py/novamoc/domain/events/controllers/_events.py` — build the bundle and call `dispatch` instead of `validate_event_values`; accept `request: Request` so handlers receive `auth`.
- `tests/events/test_validators.py` — rewrite around the new public `validate_values` surface; rename predicate imports.
- `tests/data/scenarios.py` — add `ACTIVE_OIL_CHANGE_WITH_NOTES` for the maintenance-record handler tests.
- `tests/data/fixtures/oil_change/maintenance_record_type.json` (new) and `tests/data/fixtures/oil_change/maintenance_record_type_field__notes.json` (new) — the underlying fixture atoms.
- `CLAUDE.md` — add an "Events endpoint (`POST /events`)" section mirroring the schema-endpoint subsection.

The `event_services` fixture stays local to each test file rather than promoted to `tests/conftest.py`: `test_bundle.py` needs a spy-injected variant for cache-hit assertions, and the handler test files use the same plain construction. Two ~5-line fixtures aren't worth a conftest indirection.

---

## Task 1: Rewrite `_validators.py` around a sync `validate_values`

**Files:**
- Modify: `src/py/novamoc/domain/events/_validators.py`
- Modify: `tests/events/test_validators.py`

The PR #64 module exposes `validate_event_values` (async orchestrator) plus per-key async helpers (`_validate_col_key`, `_validate_user_field_key`). The new public surface is one sync function that takes a fully-loaded `fields_by_id` map and validates the whole `values` dict. Two predicates (`json_type_name`, `matches_data_type`) are promoted to public so handler-level tests and future callers can reach them.

- [ ] **Step 1: Write the failing unit tests against the new public surface**

Replace the body of `tests/events/test_validators.py` with the matrix below. The file should import only the new public names; the test class uses a hand-built `fields_by_id` dict so no DB/event-service fixtures are needed.

```python
"""Unit tests for the public validator surface (M1.4 reshape)."""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID, uuid4

import pytest

from novamoc.db.models.schema._types import FieldDataType
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._errors import UnknownFieldError, ValueTypeMismatchError
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.events._validators import (
    json_type_name,
    matches_data_type,
    validate_values,
)


@dataclasses.dataclass
class _FieldRow:
    """Stand-in for AssetTypeField / MaintenanceRecordTypeField in unit tests.

    The validator only reads ``id``, ``parent_id``, ``data_type`` and ``active``
    — exposing those four attributes is enough for shape-level tests.
    """
    id: UUID
    parent_id: UUID
    data_type: FieldDataType
    active: bool = True


_TYPE_ID = UUID("11111111-1111-1111-1111-111111111111")


def _event(family: EntityFamily = EntityFamily.ASSET) -> EventEnvelope:
    return EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=family,
        type_id=_TYPE_ID,
        instance_id=uuid4(),
        body=Created(values={}),
    )


def _values(values: dict[str, Any]) -> None:
    """Drive validate_values against ``_TYPE_ID`` with one user field of TEXT."""
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {
        field_id: _FieldRow(id=field_id, parent_id=_TYPE_ID, data_type=FieldDataType.TEXT)
    }
    validate_values(event=_event(), values=values, fields_by_id=fields_by_id)


# --- json_type_name -----------------------------------------------------------

def test_json_type_name_distinguishes_bool_from_int() -> None:
    assert json_type_name(True) == "boolean"
    assert json_type_name(1) == "integer"


def test_json_type_name_null() -> None:
    assert json_type_name(None) == "null"


def test_json_type_name_string() -> None:
    assert json_type_name("x") == "string"


# --- matches_data_type --------------------------------------------------------

def test_matches_null_against_any_type() -> None:
    for dt in FieldDataType:
        assert matches_data_type(None, dt) is True


def test_matches_integer_rejects_bool() -> None:
    assert matches_data_type(True, FieldDataType.INTEGER) is False


def test_matches_number_rejects_bool() -> None:
    assert matches_data_type(False, FieldDataType.NUMBER) is False


def test_matches_text_rejects_int() -> None:
    assert matches_data_type(1, FieldDataType.TEXT) is False


# --- validate_values: user-field keys ----------------------------------------

def test_valid_user_field_accepted() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    _values({str(field_id): "ok"})


def test_unknown_user_field_raises_unknown_field() -> None:
    with pytest.raises(UnknownFieldError) as exc:
        _values({str(uuid4()): "x"})
    assert exc.value.extras["family"] == "asset"
    assert exc.value.extras["type_id"] == str(_TYPE_ID)


def test_wrong_user_field_type_raises_value_type_mismatch() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    with pytest.raises(ValueTypeMismatchError) as exc:
        _values({str(field_id): 42})
    assert exc.value.extras == {
        "field": str(field_id),
        "expected": "text",
        "received": "integer",
    }


def test_tombstoned_user_field_still_accepted() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {
        field_id: _FieldRow(
            id=field_id, parent_id=_TYPE_ID, data_type=FieldDataType.TEXT, active=False
        )
    }
    validate_values(
        event=_event(), values={str(field_id): "still works"}, fields_by_id=fields_by_id
    )


def test_non_uuid_non_col_key_raises_payload_shape_error() -> None:
    with pytest.raises(PayloadShapeError) as exc:
        _values({"not-a-uuid": "x"})
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE
    assert exc.value.extras["field"] == "not-a-uuid"


# --- validate_values: col: keys ----------------------------------------------

def test_user_writable_col_name_accepts_text() -> None:
    validate_values(event=_event(), values={"col:name": "Truck-7"}, fields_by_id={})


def test_user_writable_col_name_rejects_int() -> None:
    with pytest.raises(ValueTypeMismatchError) as exc:
        validate_values(event=_event(), values={"col:name": 1}, fields_by_id={})
    assert exc.value.extras["expected"] == "text"
    assert exc.value.extras["received"] == "integer"


def test_unknown_col_raises_unknown_field() -> None:
    with pytest.raises(UnknownFieldError) as exc:
        validate_values(event=_event(), values={"col:bogus": "x"}, fields_by_id={})
    assert exc.value.extras["field"] == "col:bogus"


@pytest.mark.parametrize(
    "reserved", ["col:type_id", "col:asset_id", "col:deleted", "col:row_state_hlc"]
)
def test_reserved_col_raises_payload_shape_error(reserved: str) -> None:
    with pytest.raises(PayloadShapeError) as exc:
        validate_values(event=_event(), values={reserved: "x"}, fields_by_id={})
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE
    assert exc.value.extras["field"] == reserved


# --- validate_values: empty / Updated bodies ---------------------------------

def test_empty_values_dict_is_noop() -> None:
    validate_values(event=_event(), values={}, fields_by_id={})


def test_updated_event_with_null_clears_cell() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {
        field_id: _FieldRow(id=field_id, parent_id=_TYPE_ID, data_type=FieldDataType.INTEGER)
    }
    event = EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=EntityFamily.ASSET,
        type_id=_TYPE_ID,
        instance_id=uuid4(),
        body=Updated(values={str(field_id): None}),
    )
    validate_values(event=event, values=event.body.values, fields_by_id=fields_by_id)
```

- [ ] **Step 2: Run the tests and confirm they fail**

```sh
uv run pytest tests/events/test_validators.py -v
```

Expected: ImportError on `validate_values` / `json_type_name` / `matches_data_type` (private names today).

- [ ] **Step 3: Rewrite `_validators.py`**

Replace the file contents with:

```python
"""Shared validation helpers for the events endpoint (M1.4).

Public surface:

* :func:`validate_values` — sync. Iterates a values dict, classifies each
  key (UUID user field vs ``col:<name>`` projection column), and validates
  the value's JSON shape against the field's declared ``FieldDataType``.
  Raises one of the M1.4 error types on the first offending key.
* :func:`matches_data_type` / :func:`json_type_name` — pure predicates,
  exposed for handler-level tests and future callers.

The handler is responsible for loading the type's field set and passing
it via ``fields_by_id``. The validator does no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from novamoc.db.models.schema._types import FieldDataType
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._errors import (
    UnknownFieldError,
    ValueTypeMismatchError,
)
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from novamoc.db.models.schema import AssetTypeField, MaintenanceRecordTypeField
    from novamoc.domain.events._payloads import EventEnvelope


__all__ = ("json_type_name", "matches_data_type", "validate_values")


_COL_PREFIX: Final = "col:"

_RESERVED_COLS: Final[frozenset[str]] = frozenset(
    {"type_id", "asset_id", "deleted", "row_state_hlc"}
)

_USER_WRITABLE_COLS: Final[dict[EntityFamily, dict[str, FieldDataType]]] = {
    EntityFamily.ASSET: {"name": FieldDataType.TEXT},
    EntityFamily.MAINTENANCE_RECORD: {"name": FieldDataType.TEXT},
}

# bool comes first — ``bool`` is an ``int`` subclass and would otherwise
# resolve to "integer".
_JSON_TYPE_LABELS: Final[tuple[tuple[type, str], ...]] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
)


def json_type_name(value: Any) -> str:
    """Human-readable JSON type label for problem-details ``received``."""
    if value is None:
        return "null"
    for cls, label in _JSON_TYPE_LABELS:
        if isinstance(value, cls):
            return label
    return type(value).__name__


def _is_text(v: Any) -> bool:
    return isinstance(v, str)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_integer(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_boolean(v: Any) -> bool:
    return isinstance(v, bool)


_DATA_TYPE_PREDICATES: Final[dict[FieldDataType, "Callable[[Any], bool]"]] = {
    FieldDataType.TEXT: _is_text,
    FieldDataType.NUMBER: _is_number,
    FieldDataType.INTEGER: _is_integer,
    FieldDataType.BOOLEAN: _is_boolean,
    FieldDataType.DATE: _is_text,
    FieldDataType.DATETIME: _is_text,
}


def matches_data_type(value: Any, data_type: FieldDataType) -> bool:
    """Whether ``value``'s JSON shape matches ``data_type``.

    ``None`` is always a match — it is the cell-clearing sentinel.
    """
    if value is None:
        return True
    return _DATA_TYPE_PREDICATES[data_type](value)


def _check_value(*, field: str, value: Any, data_type: FieldDataType) -> None:
    if not matches_data_type(value, data_type):
        raise ValueTypeMismatchError(
            field=field,
            expected=data_type.value,
            received=json_type_name(value),
        )


def _validate_col(
    *,
    event: "EventEnvelope",
    key: str,
    value: Any,
) -> None:
    col_name = key[len(_COL_PREFIX):]
    if col_name in _RESERVED_COLS:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"Field {key!r} is server-managed and cannot be set on the wire.",
            field=key,
        )
    family_cols = _USER_WRITABLE_COLS.get(event.family, {})
    data_type = family_cols.get(col_name)
    if data_type is None:
        raise UnknownFieldError(
            family=event.family.value,
            type_id=str(event.type_id),
            field=key,
        )
    _check_value(field=key, value=value, data_type=data_type)


def _validate_user_field(
    *,
    event: "EventEnvelope",
    key: str,
    value: Any,
    fields_by_id: "Mapping[UUID, AssetTypeField | MaintenanceRecordTypeField]",
) -> None:
    try:
        field_id = UUID(key)
    except ValueError as exc:
        raise PayloadShapeError(
            code=ErrorCode.INVALID_PAYLOAD_SHAPE,
            message=f"Field key {key!r} is neither a UUID nor a 'col:' column.",
            field=key,
        ) from exc
    field = fields_by_id.get(field_id)
    if field is None:
        raise UnknownFieldError(
            family=event.family.value,
            type_id=str(event.type_id),
            field=key,
        )
    _check_value(field=key, value=value, data_type=field.data_type)


def validate_values(
    *,
    event: "EventEnvelope",
    values: "Mapping[str, Any]",
    fields_by_id: "Mapping[UUID, AssetTypeField | MaintenanceRecordTypeField]",
) -> None:
    """Validate every (key, value) pair against the preloaded field set.

    Iterates ``values``; classifies each key as a UUID (looked up in
    ``fields_by_id``) or ``col:<name>`` (matched against the static
    reserved / user-writable tables). Raises on the first offending key:

    Raises:
        PayloadShapeError: key is malformed (not a UUID, not ``col:<known>``)
            or addresses a reserved server-managed column.
        UnknownFieldError: a UUID field id is not in ``fields_by_id`` (so it
            does not belong to ``event.type_id``), or a ``col:`` column is
            not in :data:`_USER_WRITABLE_COLS`.
        ValueTypeMismatchError: a value's JSON shape does not match the
            field's declared ``FieldDataType``.
    """
    for key, value in values.items():
        if key.startswith(_COL_PREFIX):
            _validate_col(event=event, key=key, value=value)
        else:
            _validate_user_field(
                event=event, key=key, value=value, fields_by_id=fields_by_id
            )
```

- [ ] **Step 4: Run the new unit tests and confirm they pass**

```sh
uv run pytest tests/events/test_validators.py -v
```

Expected: every test in the new file passes.

- [ ] **Step 5: Re-run the e2e tests to confirm they still depend on the old orchestrator (and will fail to import)**

```sh
uv run pytest tests/events/test_endpoint_validation.py -v
```

Expected: import error in `controllers/_events.py` because `validate_event_values` no longer exists. This is the broken intermediate state — Task 5 reconnects the controller.

- [ ] **Step 6: Commit**

```sh
git add src/py/novamoc/domain/events/_validators.py tests/events/test_validators.py
git commit -m "$(cat <<'EOF'
refactor(events/validators): synchronous validate_values over preloaded field map

Replaces the per-key async orchestrator with one sync entry point that
takes a fully-loaded fields_by_id map. Predicates promoted to public
(json_type_name, matches_data_type) so handler-level tests can reach
them without traversing private internals.

Controller is intentionally left disconnected by this commit; the
handler dispatch (next task) reconnects it.
EOF
)"
```

---

## Task 2: Add `EventServiceBundle` with per-request field caching

**Files:**
- Create: `src/py/novamoc/domain/events/_bundle.py`
- Create: `tests/events/test_bundle.py`

The bundle aggregates the two field services and owns a request-scoped memo keyed on `(family, type_id)`. Frozen + slots, with the memo as a `field(default_factory=dict)` — `frozen=True` blocks re-binding the attribute but does not block mutating the dict it points at.

- [ ] **Step 1: Write the failing bundle test**

```python
"""Tests for EventServiceBundle: cache hit/miss accounting and content."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._payloads import EntityFamily
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_TRUCK_WITH_VIN_FIELD

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class _CountingAssetTypeFieldService(AssetTypeFieldService):
    """Spy that counts list() invocations for the cache-hit test."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.list_calls = 0

    async def list(self, *args: object, **kwargs: object):  # type: ignore[override]
        self.list_calls += 1
        return await super().list(*args, **kwargs)


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=_CountingAssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
    )


async def test_fields_for_returns_type_fields_keyed_by_id(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    fields_by_id = await event_services.fields_for(EntityFamily.ASSET, type_id)
    assert set(fields_by_id) == set(ids["asset_type_field"].values())
    assert all(f.parent_id == type_id for f in fields_by_id.values())


async def test_fields_for_is_memoised_per_key(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    first = await event_services.fields_for(EntityFamily.ASSET, type_id)
    second = await event_services.fields_for(EntityFamily.ASSET, type_id)
    assert first is second  # same dict object on second call
    spy = event_services.asset_type_field_service
    assert isinstance(spy, _CountingAssetTypeFieldService)
    assert spy.list_calls == 1


async def test_fields_for_routes_to_family_specific_service(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    # Loading asset fields must not touch the maintenance-record service.
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    await event_services.fields_for(EntityFamily.ASSET, type_id)
    spy = event_services.asset_type_field_service
    assert isinstance(spy, _CountingAssetTypeFieldService)
    assert spy.list_calls == 1
```

- [ ] **Step 2: Run and confirm import error**

```sh
uv run pytest tests/events/test_bundle.py -v
```

Expected: ImportError on `novamoc.domain.events._bundle`.

- [ ] **Step 3: Write `_bundle.py`**

```python
"""Per-request aggregator of services + the field-set memo handlers use.

Lives here rather than in ``_dispatch`` or ``_handlers/__init__`` so both
can import it without setting up a circular dependency. The bundle is
built once per request in :class:`EventsController.append` and lives for
the duration of that handler call — schema cannot change mid-request, so
the memo has no invalidation surface.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from novamoc.db.models.schema import AssetTypeField, MaintenanceRecordTypeField
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._payloads import EventEnvelope
    from novamoc.domain.schema.services import (
        AssetTypeFieldService,
        MaintenanceRecordTypeFieldService,
    )


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
        """Return ``type_id``'s field set, loading once per request.

        Subsequent calls for the same ``(family, type_id)`` return the
        cached dict without a DB round-trip.
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
        loaded = {row.id: row for row in rows}
        self._fields_cache[key] = loaded
        return loaded


# Lazily-evaluated alias so the names used here can stay under TYPE_CHECKING.
type Handler = Callable[[EventServiceBundle, "RequestAuth", "EventEnvelope"], Awaitable[None]]


__all__ = ("EventServiceBundle", "Handler")
```

- [ ] **Step 4: Run and confirm bundle tests pass**

```sh
uv run pytest tests/events/test_bundle.py -v
```

Expected: three passing tests.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/_bundle.py tests/events/test_bundle.py
git commit -m "$(cat <<'EOF'
feat(events/bundle): EventServiceBundle with per-request field-set memo

services.fields_for(family, type_id) loads the type's field set once
per request and serves subsequent calls from a dict on the bundle. The
bundle is frozen + slotted; the memo lives as a default_factory dict
so frozen=True keeps the attribute pin-down without blocking mutation
of the contained dict.

The Handler type alias also lives here so _dispatch and _handlers can
both import it without a cycle.
EOF
)"
```

---

## Task 3: Add per-event handlers

**Files:**
- Create: `src/py/novamoc/domain/events/_handlers/__init__.py`
- Create: `src/py/novamoc/domain/events/_handlers/asset.py`
- Create: `src/py/novamoc/domain/events/_handlers/maintenance_record.py`
- Create: `tests/events/test_handlers_asset.py`
- Create: `tests/events/test_handlers_maintenance_record.py`

Each handler is one module-level async function. `created` / `updated` load the type's field set (via the bundle memo) and call `validate_values`. `deactivated` / `activated` are no-ops in M1.4 — they exist so the dispatch table is complete.

- [ ] **Step 1: Write the failing handler tests for asset**

```python
"""Handler-level tests for the asset family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.domain.events._handlers import asset
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._errors import (
    UnknownFieldError,
    ValueTypeMismatchError,
)
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_TRUCK_WITH_VIN_FIELD

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.accounts import RequestAuth


_HLC = "0000000000000001-00000-client-a"


def _auth() -> RequestAuth:
    from novamoc.domain.accounts import RequestAuth as _A

    return _A(tenant_id="t1")


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
    )


def _envelope(
    type_id: UUID,
    body: Created | Updated | Deactivated | Activated,
) -> EventEnvelope:
    return EventEnvelope(
        hlc=_HLC,
        family=EntityFamily.ASSET,
        type_id=type_id,
        instance_id=uuid4(),
        body=body,
    )


async def test_created_with_valid_values(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    field_id = ids["asset_type_field"]["vin"]
    body = Created(values={str(field_id): "ABC123"})
    await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_unknown_field_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    body = Created(values={str(uuid4()): "x"})
    with pytest.raises(UnknownFieldError):
        await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_wrong_value_type_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    # Truck's "vin" field is TEXT in the scenario; sending an int triggers shape mismatch.
    field_id = ids["asset_type_field"]["vin"]
    body = Created(values={str(field_id): 42})
    with pytest.raises(ValueTypeMismatchError):
        await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_updated_validates_like_created(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    field_id = ids["asset_type_field"]["vin"]
    body = Updated(values={str(field_id): None})  # null clears
    await asset.updated(event_services, _auth(), _envelope(type_id, body))


async def test_deactivated_is_noop(event_services: EventServiceBundle) -> None:
    body = Deactivated()
    await asset.deactivated(event_services, _auth(), _envelope(uuid4(), body))


async def test_activated_is_noop(event_services: EventServiceBundle) -> None:
    body = Activated()
    await asset.activated(event_services, _auth(), _envelope(uuid4(), body))
```

- [ ] **Step 2: Run and confirm import error**

```sh
uv run pytest tests/events/test_handlers_asset.py -v
```

Expected: ImportError on `novamoc.domain.events._handlers`.

- [ ] **Step 3: Write the handler package init (empty)**

```python
# src/py/novamoc/domain/events/_handlers/__init__.py
```

- [ ] **Step 4: Write `_handlers/asset.py`**

```python
"""Asset-family event handlers.

Each function is one cell of the (family, body_type) dispatch matrix
(see ``_dispatch.py``). In M1.4 the handlers do field/value validation
only; persistence and projection writes arrive with M1.5+ in the same
cells.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    Updated,
)
from novamoc.domain.events._validators import validate_values

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle
    from novamoc.domain.events._payloads import EventEnvelope


async def created(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast(Created, event.body)
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast(Updated, event.body)
    fields_by_id = await services.fields_for(EntityFamily.ASSET, event.type_id)
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def deactivated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    # Row-state event; no field/value payload. M1.5+ adds the deactivate path.
    _ = (services, auth, event, Deactivated)


async def activated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    # Row-state event; no field/value payload. M1.5+ adds the activate path.
    _ = (services, auth, event, Activated)
```

- [ ] **Step 5: Run and confirm asset handler tests pass**

```sh
uv run pytest tests/events/test_handlers_asset.py -v
```

Expected: six passing tests.

- [ ] **Step 6: Write `_handlers/maintenance_record.py`**

```python
"""Maintenance-record-family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    Updated,
)
from novamoc.domain.events._validators import validate_values

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle
    from novamoc.domain.events._payloads import EventEnvelope


async def created(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast(Created, event.body)
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def updated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    body = cast(Updated, event.body)
    fields_by_id = await services.fields_for(
        EntityFamily.MAINTENANCE_RECORD, event.type_id
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)


async def deactivated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    _ = (services, auth, event, Deactivated)


async def activated(
    services: EventServiceBundle, auth: RequestAuth, event: EventEnvelope
) -> None:
    _ = (services, auth, event, Activated)
```

- [ ] **Step 7a: Add the maintenance-record fixture atoms**

The repo currently has no maintenance-record fixtures, so the handler tests cannot seed one without us adding them. Create both files:

`tests/data/fixtures/oil_change/maintenance_record_type.json`:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000020",
    "name": "OilChange",
    "active": true
  }
]
```

`tests/data/fixtures/oil_change/maintenance_record_type_field__notes.json`:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000021",
    "parent_id": "00000000-0000-0000-0000-000000000020",
    "name": "notes",
    "data_type": "text",
    "validation": null,
    "active": true
  }
]
```

- [ ] **Step 7b: Register the scenario**

Append to `tests/data/scenarios.py`:

```python
ACTIVE_OIL_CHANGE_WITH_NOTES: Scenario = (
    "oil_change/maintenance_record_type",
    "oil_change/maintenance_record_type_field__notes",
)
```

- [ ] **Step 7c: Write `tests/events/test_handlers_maintenance_record.py`**

```python
"""Handler-level tests for the maintenance-record family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.domain.events._handlers import maintenance_record
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._errors import (
    UnknownFieldError,
    ValueTypeMismatchError,
)
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_OIL_CHANGE_WITH_NOTES

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.accounts import RequestAuth


_HLC = "0000000000000001-00000-client-a"


def _auth() -> RequestAuth:
    from novamoc.domain.accounts import RequestAuth as _A

    return _A(tenant_id="t1")


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
    )


def _envelope(
    type_id: UUID,
    body: Created | Updated | Deactivated | Activated,
) -> EventEnvelope:
    return EventEnvelope(
        hlc=_HLC,
        family=EntityFamily.MAINTENANCE_RECORD,
        type_id=type_id,
        instance_id=uuid4(),
        body=body,
    )


async def test_created_with_valid_values(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Created(values={str(field_id): "All filters replaced."})
    await maintenance_record.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_unknown_field_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    body = Created(values={str(uuid4()): "x"})
    with pytest.raises(UnknownFieldError):
        await maintenance_record.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_wrong_value_type_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Created(values={str(field_id): 42})
    with pytest.raises(ValueTypeMismatchError):
        await maintenance_record.created(event_services, _auth(), _envelope(type_id, body))


async def test_updated_validates_like_created(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Updated(values={str(field_id): None})
    await maintenance_record.updated(event_services, _auth(), _envelope(type_id, body))


async def test_deactivated_is_noop(event_services: EventServiceBundle) -> None:
    body = Deactivated()
    await maintenance_record.deactivated(event_services, _auth(), _envelope(uuid4(), body))


async def test_activated_is_noop(event_services: EventServiceBundle) -> None:
    body = Activated()
    await maintenance_record.activated(event_services, _auth(), _envelope(uuid4(), body))
```

- [ ] **Step 8: Run all handler tests**

```sh
uv run pytest tests/events/test_handlers_asset.py tests/events/test_handlers_maintenance_record.py -v
```

Expected: 12 passing tests.

- [ ] **Step 9: Commit**

```sh
git add src/py/novamoc/domain/events/_handlers/ tests/events/test_handlers_asset.py tests/events/test_handlers_maintenance_record.py tests/data/scenarios.py
git commit -m "$(cat <<'EOF'
feat(events/handlers): per-(family, body_type) handler functions

Eight handler functions across two modules: created/updated/deactivated/
activated for each of the asset and maintenance_record families.
created/updated load the type's field set via services.fields_for and
delegate to validate_values; deactivated/activated are no-ops that hold
the cell open for M1.5+ persistence work.
EOF
)"
```

---

## Task 4: Add the dispatch table

**Files:**
- Create: `src/py/novamoc/domain/events/_dispatch.py`
- Create: `tests/events/test_dispatch.py`

`_HANDLERS` keys on `(family, type(body))` because the body type alone isn't enough — the same `Created` class targets either family. The coverage test iterates `EntityFamily × get_args(EventBody)` and asserts every cell is present, so a new family or event type that lands without a handler fails in CI.

- [ ] **Step 1: Write the failing dispatch test**

```python
"""Tests for the events dispatch table."""

from __future__ import annotations

from typing import get_args

from novamoc.domain.events import _payloads
from novamoc.domain.events._dispatch import _HANDLERS
from novamoc.domain.events._payloads import EntityFamily, EventBody


def test_handlers_cover_every_family_body_pair() -> None:
    expected = {
        (family, body_type)
        for family in EntityFamily
        for body_type in get_args(EventBody)
    }
    assert set(_HANDLERS) == expected


def test_handlers_table_is_at_least_two_families_times_four_bodies() -> None:
    # Safety net in case EventBody loses a member without _HANDLERS being updated.
    assert len(_HANDLERS) == 8


async def test_dispatch_routes_created_to_asset_created(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    import novamoc.domain.events._dispatch as dispatch_mod
    from novamoc.domain.events._handlers import asset

    called: list[str] = []

    async def _fake(*_args, **_kwargs) -> None:
        called.append("asset.created")

    monkeypatch.setitem(
        dispatch_mod._HANDLERS,
        (EntityFamily.ASSET, _payloads.Created),
        _fake,
    )
    # Restore: monkeypatch unwinds automatically. The fake replaces asset.created
    # for the duration of this test.
    from uuid import uuid4

    event = _payloads.EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=EntityFamily.ASSET,
        type_id=uuid4(),
        instance_id=uuid4(),
        body=_payloads.Created(values={}),
    )
    await dispatch_mod.dispatch(services=None, auth=None, event=event)  # type: ignore[arg-type]
    assert called == ["asset.created"]
    _ = asset.created  # quiet "imported but unused" if static checker is strict
```

- [ ] **Step 2: Run and confirm import error**

```sh
uv run pytest tests/events/test_dispatch.py -v
```

Expected: ImportError on `novamoc.domain.events._dispatch`.

- [ ] **Step 3: Write `_dispatch.py`**

```python
"""Per-event handler dispatch.

The handler table is enumerated explicitly below. Each
``(family, body_type)`` cell maps to the function that handles it.
Adding a new event body or family means writing the handler in the
appropriate ``_handlers/<family>.py`` module, then adding one row
here — the universe of accepted (family, body_type) pairs is one
``rg``-able place (Zen of Python item 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.domain.events import _payloads
from novamoc.domain.events._handlers import asset, maintenance_record
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.events._bundle import EventServiceBundle, Handler
    from novamoc.domain.events._payloads import EventEnvelope


__all__ = ("dispatch",)


_HANDLERS: dict[tuple[EntityFamily, type], "Handler"] = {
    (EntityFamily.ASSET, _payloads.Created): asset.created,
    (EntityFamily.ASSET, _payloads.Updated): asset.updated,
    (EntityFamily.ASSET, _payloads.Deactivated): asset.deactivated,
    (EntityFamily.ASSET, _payloads.Activated): asset.activated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Created): maintenance_record.created,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Updated): maintenance_record.updated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Deactivated): maintenance_record.deactivated,
    (EntityFamily.MAINTENANCE_RECORD, _payloads.Activated): maintenance_record.activated,
}


async def dispatch(
    services: "EventServiceBundle",
    auth: "RequestAuth",
    event: "EventEnvelope",
) -> None:
    await _HANDLERS[(event.family, type(event.body))](services, auth, event)
```

- [ ] **Step 4: Run and confirm dispatch tests pass**

```sh
uv run pytest tests/events/test_dispatch.py -v
```

Expected: three passing tests.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/_dispatch.py tests/events/test_dispatch.py
git commit -m "$(cat <<'EOF'
feat(events/dispatch): explicit (family, body_type) handler table

dict[(EntityFamily, type[EventBody]), Handler] with eight entries.
dispatch(services, auth, event) routes via type(event.body), so the
runtime narrowing matches the table key exactly. Coverage test
catches a missing handler if EventBody or EntityFamily grows a
member.
EOF
)"
```

---

## Task 5: Switch the controller to dispatch

**Files:**
- Modify: `src/py/novamoc/domain/events/controllers/_events.py`

This commit puts the endpoint back together. The controller stops importing `validate_event_values`, builds an `EventServiceBundle`, and replaces the per-event validation call with `await dispatch(services, auth, event)`. It gains `request: Request` so the handler can pull `request.auth` (mirroring the schema controller).

- [ ] **Step 1: Re-run the e2e suite to confirm it's currently red**

```sh
uv run pytest tests/events/test_endpoint_validation.py -v
```

Expected: ImportError or runtime AttributeError because `validate_event_values` no longer exists (Task 1).

- [ ] **Step 2: Rewrite `controllers/_events.py`**

```python
"""HTTP controller for ``/events`` (ADR-013).

The controller enforces three pre-persistence batch gates and then
delegates each event to its handler:

1. **Schema-version gate** (batch-level, M1.3 / ADR-008 / ADR-009): the
   batch's ``schema_version`` must equal the tenant's current schema
   version. A mismatch raises ``schema_version_stale``.
2. **HLC parse + drift bound** (per-event, M1.2 / ADR-006): each event's
   ``hlc`` is parsed; an HLC whose physical component sits more than
   ``AppSettings.hlc_drift_limit_seconds`` ahead of server wall time is
   rejected as ``hlc_drift_exceeded``. Past HLCs are always accepted —
   drift is one-sided.
3. **Per-event handler dispatch** (M1.4): each event is routed to the
   handler matching ``(event.family, type(event.body))``. Today the
   handlers do field-existence + value-shape validation; M1.5+ layers
   persistence, projection writes, and business rules into the same
   cells.

The controller does not import ``_validators`` — that machinery is
called by the handlers, not by the controller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, post
from litestar.datastructures import State  # noqa: TC002  # runtime DI provider annotation
from litestar.di import Provide
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_202_ACCEPTED

from novamoc.domain.events import _payloads
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._dispatch import dispatch
from novamoc.domain.events._errors import (
    HLCDriftExceededError,
    SchemaVersionStaleError,
)
from novamoc.domain.events._hlc import HLC, HLCParseError, wall_now_ms
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
    SchemaChangeLogService,
)

if TYPE_CHECKING:
    pass


async def _provide_drift_limit_seconds(state: State) -> float:
    return state.settings.app.hlc_drift_limit_seconds


class EventsController(Controller):
    path = "/events"
    tags = ("events",)
    dependencies = (
        {"drift_limit_seconds": Provide(_provide_drift_limit_seconds)}
        | providers.create_service_dependencies(
            SchemaChangeLogService, "schema_change_log_service"
        )
        | providers.create_service_dependencies(
            AssetTypeFieldService, "asset_type_field_service"
        )
        | providers.create_service_dependencies(
            MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service"
        )
    )

    @post("/", status_code=HTTP_202_ACCEPTED)
    async def append(
        self,
        data: _payloads.EventBatch,
        request: Request,
        drift_limit_seconds: float,
        schema_change_log_service: SchemaChangeLogService,
        asset_type_field_service: AssetTypeFieldService,
        maintenance_record_type_field_service: MaintenanceRecordTypeFieldService,
    ) -> None:
        # 1. Batch-level schema-version gate. Runs before HLC parsing so a
        # stale-schema client sees the actionable error (re-fetch /schema)
        # instead of a downstream HLC complaint.
        current_version = await schema_change_log_service.current_version()
        if data.schema_version != current_version:
            raise SchemaVersionStaleError(
                expected=current_version,
                received=data.schema_version,
            )

        # One server-now read covers the whole batch so an event at the
        # edge of the drift budget cannot get re-checked against a later
        # server time mid-iteration.
        server_now_ms = wall_now_ms()
        limit_ms = int(drift_limit_seconds * 1000)

        services = EventServiceBundle(
            asset_type_field_service=asset_type_field_service,
            maintenance_record_type_field_service=maintenance_record_type_field_service,
        )

        for event in data.events:
            # 2. Per-event envelope check (HLC parse + drift bound).
            try:
                parsed = HLC.parse(event.hlc)
            except HLCParseError as exc:
                raise ValidationException(detail=str(exc)) from exc
            drift_ms = parsed.physical_ms - server_now_ms
            if drift_ms > limit_ms:
                raise HLCDriftExceededError(
                    hlc=event.hlc,
                    drift_seconds=drift_ms / 1000,
                    limit_seconds=drift_limit_seconds,
                )

            # 3. Dispatch to the (family, body_type) handler.
            await dispatch(services, request.auth, event)
```

- [ ] **Step 3: Run the full events test surface**

```sh
uv run pytest tests/events/ -v
```

Expected: every test passes — the existing 12 e2e tests in `test_endpoint_validation.py` go green again, all the new unit/handler/dispatch/bundle tests stay green.

- [ ] **Step 4: Run the full test suite to catch incidental breakage**

```sh
uv run pytest -q
```

Expected: green across the suite.

- [ ] **Step 5: Commit**

```sh
git add src/py/novamoc/domain/events/controllers/_events.py
git commit -m "$(cat <<'EOF'
refactor(events/controller): envelope gates + dispatch, no inline validation

Controller now enforces schema-version (batch), HLC parse + drift
(per event), then dispatches each event to its (family, body_type)
handler. Builds the EventServiceBundle once per request so handlers
share the field-set memo. request.auth flows through dispatch into
the handlers for M1.5+ persistence callsites.
EOF
)"
```

---

## Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Add an "Events endpoint (`POST /events`)" subsection mirroring the existing "Schema endpoint" subsection so future readers learn the dispatch pattern from the project root.

- [ ] **Step 1: Open `CLAUDE.md` and locate the "Schema read endpoint (`GET /schema`)" subsection.** The new section goes immediately after it.

- [ ] **Step 2: Insert this section after the schema-read subsection**

```markdown
## Events endpoint (`POST /events`)

Companion to the schema endpoint and the only fully implemented write
path for **data** events (ADR-002 / ADR-011 / ADR-013). The controller
enforces three pre-persistence gates and then routes each event to its
handler:

1. **Schema-version gate** (batch-level, ADR-008 / ADR-009) — the
   batch's ``schema_version`` must equal the tenant's current schema
   version, or the whole batch is rejected as ``schema_version_stale``.
2. **HLC parse + drift bound** (per-event, ADR-006) — each event's
   ``hlc`` is parsed; an HLC more than ``hlc_drift_limit_seconds`` ahead
   of server wall time raises ``hlc_drift_exceeded``. Past HLCs are
   always accepted.
3. **Per-event handler dispatch** (M1.4) — each event is routed via
   ``_HANDLERS[(event.family, type(event.body))]``; today the handlers
   do field-existence + value-shape validation, M1.5+ layers persistence
   and projection writes into the same cells.

Pipeline mirrors the schema endpoint's shape:

1. **Wire decode** — ``domain/events/_payloads.py`` defines
   ``EventBatch`` and the ``EventBody`` discriminated union (``Created``,
   ``Updated``, ``Deactivated``, ``Activated``) with msgspec's
   tag-field discrimination on ``event``.
2. **Service bundle** — ``domain/events/_bundle.py`` aggregates the two
   ``*TypeFieldService`` instances and owns a per-request memo
   (``fields_for(family, type_id)``) so a batch with many events on one
   type pays one ``SELECT`` for the field set.
3. **Dispatch** — ``_dispatch.py`` holds a single explicit ``_HANDLERS``
   table keyed on ``(EntityFamily, type[EventBody])``. Adding an event
   type or family requires one new handler module-level function plus
   one row in the table.
4. **Handlers** — ``_handlers/{asset,maintenance_record}.py`` expose
   ``created`` / ``updated`` / ``deactivated`` / ``activated``. M1.4
   created/updated load the type's field set via
   ``services.fields_for(...)`` and call the sync
   ``validate_values(...)``; deactivated/activated are no-ops that hold
   the cell open for M1.5+ persistence.
5. **Validators** — ``_validators.py`` exports one public sync entry
   point ``validate_values(event, values, fields_by_id)`` plus the
   ``matches_data_type`` / ``json_type_name`` predicates. The validator
   does no I/O; handlers feed it a preloaded field map.
6. **Controller** — ``controllers/_events.py`` is thin: schema-version
   gate, per-event HLC check, ``dispatch(services, auth, event)``. It
   does **not** import ``_validators`` — that's the handler's concern.

Errors flow through the same problem-details converter as the schema
endpoint. Per-event error types live in ``domain/events/_errors.py``
(``HLCDriftExceededError``, ``SchemaVersionStaleError``,
``UnknownFieldError``, ``ValueTypeMismatchError``); generic shape errors
reuse ``PayloadShapeError(code=ErrorCode.INVALID_PAYLOAD_SHAPE)``.
```

- [ ] **Step 3: Confirm the file still renders sensibly**

Read the surrounding area to make sure the insertion didn't break the section flow or duplicate a heading.

- [ ] **Step 4: Commit**

```sh
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude.md): events endpoint pipeline subsection

Documents POST /events alongside POST /schema so new readers find the
dispatch pattern, bundle memo, and validator surface from the project
root. Mirrors the structure of the schema-endpoint subsection.
EOF
)"
```

---

## Task 7: Final verification

**Files:** none modified.

- [ ] **Step 1: Run the full check pipeline**

```sh
just check
```

Expected: green. This runs ruff lint, ruff format, ty typecheck, and pytest in one composite.

- [ ] **Step 2: Inspect for leftover references to removed names**

```sh
uv run rg -n "validate_event_values|_validate_col_key|_validate_user_field_key|_values_for_validation"
```

Expected: no matches. Anything that surfaces is dead-letter and should be removed in a follow-up commit on this branch.

- [ ] **Step 3: Confirm the ratchet is unchanged or lower**

```sh
just ratchet
```

Expected: no change vs baseline, or strictly lower counts. If higher, fix the new violations before merging — do **not** bump the baseline to absorb regressions.

- [ ] **Step 4: Force-push the reshape to PR #64**

```sh
git push --force-with-lease origin HEAD
```

Force-with-lease prevents clobbering anything the remote has that you don't. If the lease fails, fetch and reconcile before retrying.
