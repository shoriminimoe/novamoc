# `POST /events` Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `EventsController`, request payload structs, and OpenAPI surface for `POST /events` per [issue #20](https://github.com/shoriminimoe/novamoc/issues/20). No validation, no projection writes, no event-log inserts — a typed handler that compiles, accepts a syntactically valid `EventBatch`, returns `202 Accepted`, and appears in `/openapi`. Subsequent issues in milestone M1 fill in validation (M1.2–M1.4), persistence (M1.5), and projection writes (M1.6–M1.8) behind this same surface.

**Architecture:** New `EventsController` mounted at `/events`, structured parallel to `domain/schema/controllers/_schema.py`. A single `_payloads.py` module exposes `EventEnvelope` (mirroring the `event_log` columns from ADR-011) and `EventBatch` (the per-tenant wire envelope). `before_send_handler="autocommit"` is already configured app-wide on the SQLAlchemy plugin in `asgi.create_app`, so the only wiring change is registering `EventsController` alongside `SchemaController` in `route_handlers`. The pre-existing 0-byte stub at `domain/events/service.py` is removed because nothing in this scope writes to the database.

**Tech Stack:** Python 3.14, Litestar, msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, pytest (asyncio auto mode), uv, ruff, ty.

---

## File map

**Created:**
- `src/py/novamoc/domain/events/_payloads.py` — `EventEnvelope` and `EventBatch` `msgspec.Struct`s. Reuses `EventOp` from `novamoc.db.models.data` (same pattern as `_payloads.py` reusing `FieldDataType` from `db.models.schema`).
- `src/py/novamoc/domain/events/controllers/__init__.py` — re-exports `EventsController`.
- `src/py/novamoc/domain/events/controllers/_events.py` — the `EventsController`.
- `tests/events/__init__.py` — empty package marker (matches `tests/schema/__init__.py`).
- `tests/events/test_payloads.py` — round-trip decode tests for `EventEnvelope` / `EventBatch`.
- `tests/events/test_endpoint_e2e.py` — E2E HTTP tests (202 happy path, 400 on malformed body).
- `tests/events/test_app_wiring.py` — smoke test that `create_app()` mounts the route.
- `tests/events/test_openapi.py` — confirms `/events` appears in the OpenAPI document with a typed `EventBatch` request body referencing both `EventBatch` and `EventEnvelope` schemas.

**Modified:**
- `src/py/novamoc/asgi.py` — add `EventsController` to `route_handlers` and import.
- `tests/conftest.py` — add `EventsController` to the test `app` fixture's `route_handlers` so HTTP tests can exercise the route.

**Deleted:**
- `src/py/novamoc/domain/events/service.py` — empty 0-byte stub from an earlier sketch; nothing imports it. A real service module lands with M1.5 (persistence).

`domain/events/` and `domain/events/controllers/` follow the same package conventions as `domain/schema/`: `domain/events/` itself is a PEP 420 namespace package (no `__init__.py`, matching `domain/schema/`), but `domain/events/controllers/` is a regular package with `__init__.py` re-exporting the controller class (matching `domain/schema/controllers/__init__.py`).

---

## Conventions

- **TDD throughout.** Every behavioural task starts with a failing test. Watch the test fail, then make it pass.
- **No DB mocks.** All DB-touching tests use the real in-memory aiosqlite (per `tests/conftest.py`). The scaffolding handler does no DB work, but the existing `client` fixture wires the SQLAlchemy plugin so the autocommit path is exercised even on a no-op handler.
- **`uv run` everything.** Tests, lint, and type-check go through `uv run` so the project's pinned deps and Python 3.14 toolchain are used.
- **`pytest` is in asyncio auto mode** — async tests do not need `@pytest.mark.asyncio`.
- **One commit per task.** Working tree is clean and tests pass at every commit boundary. Hooks are honoured (no `--no-verify`).
- **Layering rule (CLAUDE.md "Critical layering rule").** `_payloads.py` may import enums from `novamoc.db.models.data` — that subpackage uses only `advanced_alchemy.base` / `advanced_alchemy.types`, never the Litestar extension. The controller may import the Litestar-flavored extensions; the payloads module must not.

---

## Task 1: Remove the stale empty stub at `domain/events/service.py`

**Files:**
- Delete: `src/py/novamoc/domain/events/service.py`

The file is a 0-byte placeholder from before the milestone scope was finalised. Nothing imports it. Deleting it now keeps the new package layout clean and prevents a future M1.5 author from cargo-culting an empty file.

- [ ] **Step 1: Confirm the file is empty and unreferenced**

```bash
wc -c src/py/novamoc/domain/events/service.py
```

Expected: `0 src/py/novamoc/domain/events/service.py`.

```bash
uv run python -c "import ast, pathlib, sys
hits = []
for p in pathlib.Path('src/py').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and 'events.service' in n.module:
            hits.append((p, n.lineno))
        if isinstance(n, ast.Import):
            for a in n.names:
                if 'events.service' in a.name:
                    hits.append((p, n.lineno))
print(hits)"
```

Expected: `[]` — no references to `events.service`.

- [ ] **Step 2: Delete the file**

```bash
git rm src/py/novamoc/domain/events/service.py
```

- [ ] **Step 3: Verify the test suite still passes**

```bash
uv run pytest -q
```

Expected: all tests pass (the file was unreferenced).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(events): drop empty service.py stub

The 0-byte placeholder predates the M1 milestone scope. A real
service module lands with M1.5 (persistence). Removing it now keeps
the new domain/events/ layout uncluttered."
```

---

## Task 2: Add `EventEnvelope` and `EventBatch` payload tests

**Files:**
- Create: `tests/events/__init__.py` (empty, matches `tests/schema/__init__.py`)
- Create: `tests/events/test_payloads.py`

The payloads are the wire contract for the rest of M1. Round-trip tests anchor the field names, types, and optionality before any controller code is written. The handler in Task 3 takes `EventBatch` directly, so getting the shape right here is what makes the controller signature compile.

- [ ] **Step 1: Create the empty test package marker**

`tests/events/__init__.py`:

```python
```

(Empty file, matches `tests/schema/__init__.py`.)

- [ ] **Step 2: Write the failing payload tests**

`tests/events/test_payloads.py`:

```python
"""Round-trip decode tests for the events wire format.

The handler in :class:`novamoc.domain.events.controllers.EventsController`
accepts ``EventBatch`` directly, so the field names, types, and
optionality of these structs are the public contract for ``POST /events``.
"""

from __future__ import annotations

import json

import msgspec
import pytest

from novamoc.db.models.data import EventOp
from novamoc.domain.events import _payloads


_TENANT = "t1"
_HLC = "2026-05-03T12:00:00.000Z-0001-aaaaaaaaaaaaaaaa"
_ENTITY = "01958f3b-3b9f-7d3a-89aa-000000000001"
_FIELD = "01958f3b-3b9f-7d3a-89aa-000000000aaa"


def _decode_envelope(body: dict) -> _payloads.EventEnvelope:
    return msgspec.json.decode(
        json.dumps(body).encode(), type=_payloads.EventEnvelope
    )


def _decode_batch(body: dict) -> _payloads.EventBatch:
    return msgspec.json.decode(json.dumps(body).encode(), type=_payloads.EventBatch)


def test_event_envelope_set_with_value_round_trips() -> None:
    env = _decode_envelope(
        {
            "hlc": _HLC,
            "schema_version": 7,
            "table_name": "asset_field_values",
            "entity_id": _ENTITY,
            "field_id": _FIELD,
            "op": "set",
            "value_json": {"miles": 12345},
        }
    )
    assert env.hlc == _HLC
    assert env.schema_version == 7
    assert env.table_name == "asset_field_values"
    assert env.entity_id == _ENTITY
    assert env.field_id == _FIELD
    assert env.op is EventOp.SET
    assert env.value_json == {"miles": 12345}


def test_event_envelope_delete_omits_optional_fields() -> None:
    env = _decode_envelope(
        {
            "hlc": _HLC,
            "schema_version": 7,
            "table_name": "assets",
            "entity_id": _ENTITY,
            "op": "delete",
        }
    )
    assert env.op is EventOp.DELETE
    assert env.field_id is None
    assert env.value_json is None


def test_event_envelope_unknown_op_is_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode_envelope(
            {
                "hlc": _HLC,
                "schema_version": 7,
                "table_name": "assets",
                "entity_id": _ENTITY,
                "op": "patch",
            }
        )


def test_event_envelope_missing_required_field_is_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode_envelope(
            {
                # hlc missing
                "schema_version": 7,
                "table_name": "assets",
                "entity_id": _ENTITY,
                "op": "set",
            }
        )


def test_event_envelope_forbids_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode_envelope(
            {
                "hlc": _HLC,
                "schema_version": 7,
                "table_name": "assets",
                "entity_id": _ENTITY,
                "op": "set",
                "extraneous": "nope",
            }
        )


def test_event_batch_round_trips_two_events() -> None:
    batch = _decode_batch(
        {
            "tenant_id": _TENANT,
            "events": [
                {
                    "hlc": _HLC,
                    "schema_version": 7,
                    "table_name": "asset_field_values",
                    "entity_id": _ENTITY,
                    "field_id": _FIELD,
                    "op": "set",
                    "value_json": {"miles": 12345},
                },
                {
                    "hlc": _HLC + "-2",
                    "schema_version": 7,
                    "table_name": "assets",
                    "entity_id": _ENTITY,
                    "op": "delete",
                },
            ],
        }
    )
    assert batch.tenant_id == _TENANT
    assert len(batch.events) == 2
    assert batch.events[0].op is EventOp.SET
    assert batch.events[1].op is EventOp.DELETE


def test_event_batch_accepts_empty_events_list() -> None:
    # Scaffolding does no validation; the controller still returns 202
    # for a syntactically valid empty batch. Validation issues land in
    # M1.2-M1.4.
    batch = _decode_batch({"tenant_id": _TENANT, "events": []})
    assert batch.tenant_id == _TENANT
    assert batch.events == ()


def test_event_batch_forbids_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        _decode_batch(
            {"tenant_id": _TENANT, "events": [], "node_id": "client-1"}
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/events/test_payloads.py -v
```

Expected: collection error / `ModuleNotFoundError: No module named 'novamoc.domain.events._payloads'`.

- [ ] **Step 4: Commit the failing tests so the implementation diff is clean**

```bash
git add tests/events/__init__.py tests/events/test_payloads.py
git commit -m "test(events): payload round-trip tests for EventEnvelope / EventBatch

Anchors the wire contract for POST /events before the implementation
lands. Tests are red until the next commit adds the payload module."
```

---

## Task 3: Implement `EventEnvelope` and `EventBatch`

**Files:**
- Create: `src/py/novamoc/domain/events/_payloads.py`

Mirror the `event_log` columns enumerated in ADR-011 / `db/models/data/_event.py`. `tenant_id` lives at the batch level (per ADR-014's tenant-scoping convention) — not on each envelope — so a malformed batch can't mix tenants in a single request. The struct uses `tuple[EventEnvelope, ...]` for `events` to match the immutable-collection convention established by `_read_payloads.py`.

- [ ] **Step 1: Implement the payloads module**

`src/py/novamoc/domain/events/_payloads.py`:

```python
"""Wire-format request structs for ``POST /events``.

Mirrors the ``event_log`` columns enumerated in ADR-011 and
:mod:`novamoc.db.models.data._event` so the envelope and the storage
row are aligned by construction. ``tenant_id`` lives on the batch, not
on each envelope, per ADR-014 — a single request is scoped to one
tenant.

This module is request-decode only; subsequent issues in milestone M1
add validation (M1.2-M1.4), persistence (M1.5), and projection writes
(M1.6-M1.8). Keep this module storage-free so the layering rule from
``CLAUDE.md`` (db-layer / payloads must not depend on Litestar) is
preserved.

``forbid_unknown_fields=True`` rejects extraneous keys at decode time
so a typo on the wire becomes a 400 ``invalid_payload_shape`` rather
than a silently-dropped field. ``omit_defaults=True`` keeps the
optional-field defaults out of round-trip encodings.
"""

from __future__ import annotations

from typing import Any

import msgspec

from novamoc.db.models.data import EventOp


class EventEnvelope(
    msgspec.Struct, forbid_unknown_fields=True, omit_defaults=True
):
    """One event in a batch. Field set mirrors ``event_log`` (ADR-011).

    ``field_id`` is null for row-level operations; ``value_json`` is
    null for ``op=delete``. Both default to ``None`` so absent-from-wire
    decodes to a usable struct without forcing every caller to spell
    them out.
    """

    hlc: str
    schema_version: int
    table_name: str
    entity_id: str
    op: EventOp
    field_id: str | None = None
    value_json: Any | None = None


class EventBatch(msgspec.Struct, forbid_unknown_fields=True):
    """One client push: a tenant + an ordered list of events."""

    tenant_id: str
    events: tuple[EventEnvelope, ...]
```

- [ ] **Step 2: Run the payload tests to verify they pass**

```bash
uv run pytest tests/events/test_payloads.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 3: Lint and type-check the new module**

```bash
uv run ruff check src/py/novamoc/domain/events tests/events
uv run ruff format --check src/py/novamoc/domain/events tests/events
uv run ty check
```

Expected: clean (no findings).

- [ ] **Step 4: Commit**

```bash
git add src/py/novamoc/domain/events/_payloads.py
git commit -m "feat(events): EventEnvelope and EventBatch payload structs

Mirrors the event_log columns from ADR-011 / db.models.data._event
so the wire envelope and the storage row stay aligned. tenant_id is
batch-scoped per ADR-014. forbid_unknown_fields rejects typos at
decode time. Storage-free per the CLAUDE.md layering rule."
```

---

## Task 4: Write the failing E2E test for `POST /events`

**Files:**
- Create: `tests/events/test_endpoint_e2e.py`

Two cases cover the M1.1 acceptance criteria:

1. A syntactically valid batch returns `202` with no body.
2. A malformed body (unknown enum, missing required field) returns `400` with the existing `application/problem+json` envelope. This proves the existing `ProblemDetailsPlugin` already covers the new route — no per-controller exception handlers are needed.

The `client` fixture comes from `tests/conftest.py` — but that fixture currently only wires `SchemaController`. Task 6 adds `EventsController` to the fixture; until then this test is red because the route isn't mounted. Writing the test first surfaces both gaps (no controller, no fixture wiring) at once.

- [ ] **Step 1: Write the failing tests**

`tests/events/test_endpoint_e2e.py`:

```python
"""E2E tests for POST /events scaffolding (issue #20 / M1.1).

The handler does no validation, no persistence, and no projection
writes. It exists to lock down the route shape, the response status,
and the OpenAPI surface so the M1.2-M1.8 issues can fill in behavior
behind the same wire contract.
"""

from __future__ import annotations


_HLC = "2026-05-03T12:00:00.000Z-0001-aaaaaaaaaaaaaaaa"
_ENTITY = "01958f3b-3b9f-7d3a-89aa-000000000001"


async def test_post_events_accepts_batch_and_returns_202(client) -> None:
    resp = await client.post(
        "/events",
        json={
            "tenant_id": "t1",
            "events": [
                {
                    "hlc": _HLC,
                    "schema_version": 1,
                    "table_name": "assets",
                    "entity_id": _ENTITY,
                    "op": "set",
                    "value_json": {"miles": 12345},
                }
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    # Scaffolding: no body. Litestar returns an empty body for 202 when
    # the handler returns None.
    assert resp.content == b""


async def test_post_events_accepts_empty_batch(client) -> None:
    resp = await client.post(
        "/events", json={"tenant_id": "t1", "events": []}
    )
    assert resp.status_code == 202, resp.text


async def test_post_events_rejects_unknown_op_with_problem_details(
    client,
) -> None:
    resp = await client.post(
        "/events",
        json={
            "tenant_id": "t1",
            "events": [
                {
                    "hlc": _HLC,
                    "schema_version": 1,
                    "table_name": "assets",
                    "entity_id": _ENTITY,
                    "op": "patch",  # not a member of EventOp
                }
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "urn:novamoc:problems:invalid_payload_shape"


async def test_post_events_rejects_missing_required_field(client) -> None:
    resp = await client.post(
        "/events",
        json={
            "tenant_id": "t1",
            "events": [
                {
                    # hlc missing
                    "schema_version": 1,
                    "table_name": "assets",
                    "entity_id": _ENTITY,
                    "op": "set",
                }
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/events/test_endpoint_e2e.py -v
```

Expected: all four tests fail (404 from the test client because the route isn't mounted).

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/events/test_endpoint_e2e.py
git commit -m "test(events): failing E2E tests for POST /events

Anchors the M1.1 acceptance criteria: 202 on a valid batch and 400
problem-details on a malformed body. Red until the next commit
mounts EventsController."
```

---

## Task 5: Implement `EventsController`

**Files:**
- Create: `src/py/novamoc/domain/events/controllers/__init__.py`
- Create: `src/py/novamoc/domain/events/controllers/_events.py`

The controller takes `EventBatch` directly so msgspec decode happens before the handler body, and any malformed payload becomes a `msgspec.ValidationError` rendered as `application/problem+json` by the existing app-level `ProblemDetailsPlugin`. The handler returns `None` with `status_code=202`; Litestar emits an empty body. No `before_send_handler` override on the controller — `autocommit` is configured app-wide on the SQLAlchemy plugin (`asgi.create_app`, `tests/conftest.py::app`), so every route inherits it.

The 202 response advertises an empty schema in OpenAPI; the 400 response borrows the same `ProblemDetails` `ResponseSpec` shape used by `SchemaController` so the OpenAPI surface is consistent across endpoints.

- [ ] **Step 1: Implement the controller**

`src/py/novamoc/domain/events/controllers/_events.py`:

```python
"""HTTP controller for the ``/events`` route (M1.1 scaffolding).

``POST /events`` accepts an :class:`EventBatch` and returns
``202 Accepted``. No validation, no persistence, no projection writes —
the route exists so milestone M1's later issues (M1.2-M1.8) can fill
in behavior behind a stable wire contract.

Error rendering is the app-level ``ProblemDetailsPlugin`` registered
in ``novamoc.asgi.create_app`` per ADR-016: ``msgspec.ValidationError``
and Litestar's ``ValidationException`` render as
``application/problem+json``. This controller does not register its
own exception handlers.
"""

from __future__ import annotations

from litestar import Controller, post
from litestar.openapi.datastructures import ResponseSpec

from novamoc.api._problem_details import ProblemDetails
from novamoc.domain.events._payloads import EventBatch


class EventsController(Controller):
    path = "/events"
    tags = ["events"]

    @post(
        "/",
        status_code=202,
        responses={
            202: ResponseSpec(
                None,
                description="Batch accepted. Validation and persistence are M1.2-M1.5.",
            ),
            400: ResponseSpec(
                ProblemDetails,
                description="Invalid request",
                media_type="application/problem+json",
            ),
        },
    )
    async def push_batch(self, data: EventBatch) -> None:
        # Scaffolding: M1.1 only proves the wire shape. ``data`` is
        # decoded so we know it has the right field set; storage and
        # validation arrive in M1.2-M1.5.
        del data
        return None
```

`src/py/novamoc/domain/events/controllers/__init__.py`:

```python
from ._events import EventsController

__all__ = ("EventsController",)
```

- [ ] **Step 2: Run the E2E tests — they will still fail because the fixture doesn't mount the controller yet**

```bash
uv run pytest tests/events/test_endpoint_e2e.py -v
```

Expected: still 404 — fixture wiring is the next task. (You can confirm the controller imports cleanly with `uv run python -c "from novamoc.domain.events.controllers import EventsController"`.)

- [ ] **Step 3: Commit the controller**

```bash
git add src/py/novamoc/domain/events/controllers/
git commit -m "feat(events): EventsController scaffolding (M1.1)

POST /events accepts EventBatch and returns 202. No validation,
persistence, or projection writes — those land in M1.2-M1.8 behind
this wire surface. ProblemDetailsPlugin (configured app-wide)
handles msgspec/Litestar validation errors per ADR-016."
```

---

## Task 6: Wire `EventsController` into `asgi.create_app` and the test fixture

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `tests/conftest.py`

Two registration sites: the production app factory and the test `app` fixture. Both currently list only `SchemaController` in `route_handlers`. After this task the E2E tests from Task 4 turn green.

- [ ] **Step 1: Register the controller in `asgi.create_app`**

In `src/py/novamoc/asgi.py`, add the import next to the existing controller import and add the controller to `route_handlers`.

Replace:

```python
    from novamoc.domain.schema._errors import SchemaError
    from novamoc.domain.schema.controllers import SchemaController
```

with:

```python
    from novamoc.domain.events.controllers import EventsController
    from novamoc.domain.schema._errors import SchemaError
    from novamoc.domain.schema.controllers import SchemaController
```

Replace:

```python
    return Litestar(
        route_handlers=[SchemaController],
```

with:

```python
    return Litestar(
        route_handlers=[SchemaController, EventsController],
```

- [ ] **Step 2: Register the controller in the test fixture**

In `tests/conftest.py`, add the import and update the fixture's `route_handlers`.

Replace:

```python
from novamoc.domain.schema.controllers import SchemaController
```

with:

```python
from novamoc.domain.events.controllers import EventsController
from novamoc.domain.schema.controllers import SchemaController
```

Replace:

```python
    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

with:

```python
    return Litestar(
        route_handlers=[SchemaController, EventsController],
        plugins=[
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

- [ ] **Step 3: Run the E2E tests — they should now pass**

```bash
uv run pytest tests/events/test_endpoint_e2e.py -v
```

Expected: all four tests pass (202 / 202 / 400 / 400 with `application/problem+json`).

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: green; no schema or read-endpoint test regresses.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/asgi.py tests/conftest.py
git commit -m "feat(events): mount EventsController in app factory and test fixture

Registers the controller alongside SchemaController in both
asgi.create_app and the conftest test app. The autocommit handler is
already wired app-wide on SQLAlchemyAsyncConfig, so /events inherits
it without per-controller configuration."
```

---

## Task 7: Add the app-wiring smoke test

**Files:**
- Create: `tests/events/test_app_wiring.py`

Mirrors `tests/schema/test_app_wiring.py`: instantiates `create_app()` (the production factory, not the test fixture) and confirms `/events` is mounted. This catches the case where someone wires the controller into the test fixture but forgets `asgi.py`.

- [ ] **Step 1: Write the smoke test**

`tests/events/test_app_wiring.py`:

```python
"""Smoke test: novamoc.asgi.create_app mounts /events.

Mirrors tests/schema/test_app_wiring.py. The test fixture in
conftest.py builds a parallel Litestar app, so it can drift from the
production factory; this test exercises the production factory
directly so a missing route_handlers entry in asgi.py fails CI even
if the fixture was updated.
"""

from __future__ import annotations

from litestar.testing import AsyncTestClient

from novamoc.asgi import create_app


async def test_app_starts_and_post_events_route_exists() -> None:
    app = create_app()
    async with AsyncTestClient(app) as client:
        # POST /events with a malformed body should give a structured
        # 400, not a 404 — confirms the route is registered.
        resp = await client.post(
            "/events",
            json={
                "tenant_id": "t1",
                "events": [
                    {
                        # hlc missing → msgspec validation error → 400
                        "schema_version": 1,
                        "table_name": "assets",
                        "entity_id": "01958f3b-3b9f-7d3a-89aa-000000000001",
                        "op": "set",
                    }
                ],
            },
        )
        assert resp.status_code == 400, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
```

- [ ] **Step 2: Run the smoke test**

```bash
uv run pytest tests/events/test_app_wiring.py -v
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/events/test_app_wiring.py
git commit -m "test(events): smoke test that asgi.create_app mounts /events

Mirrors tests/schema/test_app_wiring.py. Catches the case where
EventsController is wired into the test fixture but forgotten in the
production app factory."
```

---

## Task 8: Add the OpenAPI surface test

**Files:**
- Create: `tests/events/test_openapi.py`

The M1.1 acceptance says `/events` must appear in `/openapi` with a typed `EventBatch` request body. Test fetches `/openapi` from the test app and asserts (a) the path is present, (b) the `requestBody` references a `EventBatch` schema component, and (c) `EventBatch.events` references an `EventEnvelope` schema component. This pins the schema surface so a future refactor can't accidentally inline the structs (which would break code generation downstream).

Litestar's default OpenAPI serialization route is JSON at `/openapi/openapi.json` (with the OpenAPI mount path moved to `/openapi` per `asgi.py` to avoid colliding with `POST /schema`).

- [ ] **Step 1: Write the OpenAPI test**

`tests/events/test_openapi.py`:

```python
"""Verify the M1.1 acceptance: POST /events appears in /openapi with
a typed EventBatch request body referencing EventEnvelope.

Pins the OpenAPI surface so a future refactor that inlines the
structs (which would break downstream code generation / docs) fails
in CI rather than silently shipping.
"""

from __future__ import annotations


async def test_openapi_exposes_post_events_with_typed_event_batch(client) -> None:
    resp = await client.get("/openapi/openapi.json")
    assert resp.status_code == 200, resp.text
    spec = resp.json()

    assert "/events" in spec["paths"], list(spec["paths"])
    post_op = spec["paths"]["/events"]["post"]

    request_body_schema = post_op["requestBody"]["content"]["application/json"][
        "schema"
    ]
    # Litestar emits "$ref" to a component; assert it points at EventBatch.
    ref = request_body_schema.get("$ref", "")
    assert ref.endswith("/EventBatch"), request_body_schema

    schemas = spec["components"]["schemas"]
    assert "EventBatch" in schemas
    assert "EventEnvelope" in schemas

    # EventBatch.events should be an array whose item references
    # EventEnvelope (via $ref or allOf wrapping a $ref). Accept both
    # shapes so the assertion isn't brittle to Litestar's $ref nesting.
    events_property = schemas["EventBatch"]["properties"]["events"]
    assert events_property["type"] == "array"
    items = events_property["items"]
    item_ref = items.get("$ref") or (
        items.get("allOf", [{}])[0].get("$ref", "") if items.get("allOf") else ""
    )
    assert item_ref.endswith("/EventEnvelope"), items


async def test_openapi_post_events_advertises_202(client) -> None:
    resp = await client.get("/openapi/openapi.json")
    spec = resp.json()
    responses = spec["paths"]["/events"]["post"]["responses"]
    assert "202" in responses, list(responses)
```

- [ ] **Step 2: Run the OpenAPI tests**

```bash
uv run pytest tests/events/test_openapi.py -v
```

Expected: both pass.

If the `$ref` shape assertion fails because Litestar nests differently than expected, debug by printing `events_property` (`pytest -s` + a `print`) and adjust the assertion to match Litestar's actual emission shape — do not loosen the assertion to `True`.

- [ ] **Step 3: Commit**

```bash
git add tests/events/test_openapi.py
git commit -m "test(events): OpenAPI exposes POST /events with typed EventBatch

Pins the M1.1 acceptance: /events is in the OpenAPI document with a
$ref to EventBatch in the request body, and the EventBatch schema
references EventEnvelope for its events array. Catches refactors
that would inline the structs and break downstream codegen."
```

---

## Task 9: Final verification

**Files:** none modified.

End-of-plan gate: run every check the project's CI surface uses (per CLAUDE.md "verification-before-completion"), confirm a clean git status, and confirm the working branch is ready for review.

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass, no warnings about uncollected items.

- [ ] **Step 2: Lint**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: clean. If `format --check` fails, run `uv run ruff format src tests` and amend the relevant commit (or commit the format fix separately if it touches multiple tasks).

- [ ] **Step 3: Type-check**

```bash
uv run ty check
```

Expected: clean.

- [ ] **Step 4: Frontend check (no SPA changes were made, but the project gate runs it)**

```bash
cd src/js/web && npm run check
```

Expected: clean (no Svelte / TypeScript regressions).

- [ ] **Step 5: Confirm clean working tree and review the branch diff**

```bash
git status
git log --oneline main..HEAD
```

Expected: clean working tree; commits in order:
1. `chore(events): drop empty service.py stub`
2. `test(events): payload round-trip tests for EventEnvelope / EventBatch`
3. `feat(events): EventEnvelope and EventBatch payload structs`
4. `test(events): failing E2E tests for POST /events`
5. `feat(events): EventsController scaffolding (M1.1)`
6. `feat(events): mount EventsController in app factory and test fixture`
7. `test(events): smoke test that asgi.create_app mounts /events`
8. `test(events): OpenAPI exposes POST /events with typed EventBatch`

- [ ] **Step 6: Manually exercise the route against the dev server (optional sanity check)**

```bash
just serve &
SERVER_PID=$!
sleep 2
curl -i -X POST http://localhost:8000/events \
  -H 'content-type: application/json' \
  -d '{"tenant_id":"t1","events":[]}'
kill $SERVER_PID
```

Expected: `HTTP/1.1 202 Accepted` with an empty body.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "M1.1: scaffold POST /events (issue #20)" --body "$(cat <<'EOF'
## Summary

Closes #20.

- Adds `EventEnvelope` / `EventBatch` msgspec structs in `domain/events/_payloads.py`, mirroring the `event_log` columns from ADR-011.
- Mounts `EventsController` at `/events` with a `POST` returning `202 Accepted`. No validation, persistence, or projection writes — those land in M1.2-M1.8 behind this wire surface.
- Inherits `before_send_handler="autocommit"` from the app-wide `SQLAlchemyAsyncConfig`; no per-controller configuration needed.
- `/openapi` exposes the new path with a typed `EventBatch` request body.

## Test plan

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check src tests`
- [ ] `uv run ruff format --check src tests`
- [ ] `uv run ty check`
- [ ] `cd src/js/web && npm run check`
- [ ] Manual: `curl -i -X POST localhost:8000/events -H 'content-type: application/json' -d '{"tenant_id":"t1","events":[]}'` → 202.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
