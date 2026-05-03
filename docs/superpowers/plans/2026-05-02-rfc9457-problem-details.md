# RFC 9457 Problem-Details Error Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc `{error, code, message, ...extras}` JSON envelope with RFC 9457 problem-details (`application/problem+json`) applied uniformly across the API.

**Architecture:** Adopt Litestar's built-in `ProblemDetailsPlugin` registered at app level. Extend `SchemaCommandError` with per-code `title` and a stable `type` URI of the form `https://novamoc.example/problems/<code>`. Define a new `ProblemDetails` msgspec struct under a new `novamoc.api` package for OpenAPI documentation. Convert `SchemaCommandError`, `msgspec.ValidationError`, and `litestar.exceptions.ValidationException` to `ProblemDetailsException` via the plugin's `exception_to_problem_detail_map`. Remove the three controller-scoped exception handlers and the legacy `SchemaErrorResponse` struct. Set `enable_for_all_http_exceptions=True` so framework-raised `HTTPException`s (e.g., 404 on a misrouted request) also render as problem-details.

The `code` field is folded into the leaf of the `type` URI (per the issue) — clients branch on the URI's leaf segment rather than a top-level `code` key. The `error` category field is dropped entirely; HTTP `status` carries the broad category.

**Tech Stack:** Python 3.14, Litestar (`ProblemDetailsPlugin`, `ProblemDetailsException`), msgspec, advanced-alchemy, pytest (asyncio auto-mode), uv, ruff, ty.

**Issue:** GitHub #8.

---

## File structure

**New files:**

- `docs/adr/016-rfc9457-problem-details-error-envelope.md` — the architectural decision record (Task 1).
- `src/py/novamoc/api/__init__.py` — empty package marker.
- `src/py/novamoc/api/_problem_details.py` — the `ProblemDetails` msgspec struct, the three exception → `ProblemDetailsException` converters, and `make_instance()` UUID helper.
- `tests/api/__init__.py` — empty.
- `tests/api/test_problem_details.py` — unit tests for the converters and the struct shape.
- `tests/schema/test_errors.py` *(may already exist as an empty/cached file — verify with `ls`; if absent, create)* — unit tests for the new `title` / `type_uri` helpers on `_errors.py`.

**Modified files:**

- `src/py/novamoc/domain/schema/_errors.py` — add `_TITLES` map, module-level `PROBLEM_TYPE_BASE`, and `title` / `type_uri` properties on `SchemaCommandError`. Drop the now-unused `error` class attribute.
- `src/py/novamoc/domain/schema/_payloads.py` — remove `SchemaErrorResponse`.
- `src/py/novamoc/domain/schema/controllers/_schema.py` — remove the three handler functions (`schema_command_error_handler`, `msgspec_validation_error_handler`, `litestar_validation_error_handler`) and the `exception_handlers` mapping; switch `responses=` mappings to reference `ProblemDetails`; rewrite the module docstring to describe the new app-level rendering layer.
- `src/py/novamoc/asgi.py` — register `ProblemDetailsPlugin` with `exception_to_problem_detail_map={SchemaCommandError, msgspec.ValidationError, ValidationException}` and `enable_for_all_http_exceptions=True`.
- `tests/conftest.py` — `app` fixture must build the app the same way `create_app()` does (or call `create_app()` and rebind the alchemy plugin); easiest is to add `ProblemDetailsPlugin` to the manually-constructed Litestar in the fixture.
- `tests/schema/test_app_wiring.py` — update assertions for the new envelope shape.
- `tests/schema/test_endpoint_e2e.py` — update assertions for the new envelope shape and `application/problem+json` content-type.
- `tests/schema/test_payloads.py` — remove `test_schema_error_response_minimal_envelope`.
- `CLAUDE.md` — update the "Schema endpoint" section: replace the envelope description and the three-handlers description with the new app-level plugin-based rendering.
- `docs/adr/013-http-and-websocket-transports.md` — add a short paragraph noting RFC 9457 problem-details is the API-wide error contract.
- `docs/superpowers/specs/2026-05-01-schema-endpoint-design.md` — replace the "Errors" and "Response envelopes" subsections to match the new shape; mark spec as revised today.

---

## Self-contained constants

Used in multiple steps below. Keep these consistent everywhere they appear:

```python
PROBLEM_TYPE_BASE = "https://novamoc.example/problems"

_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
}
```

The `type` URI for a code is `f"{PROBLEM_TYPE_BASE}/{code.value}"` — e.g., `https://novamoc.example/problems/name_reserved`.

---

## Task 1: Write ADR-016 to record the decision

The decision to adopt RFC 9457 needs a recorded ADR before the implementation citing it lands. Per the project's ADR style (cite by number, don't recap upstream facts), this is short.

**Files:**
- Create: `docs/adr/016-rfc9457-problem-details-error-envelope.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-016: RFC 9457 Problem-Details as the API Error Envelope

## Status

Proposed

## Context

The current ad-hoc HTTP error envelope (`{error, code, message, ...extras}`, used by the schema endpoint per ADR-013) carries three overlapping fields — `error` is derivable from HTTP status, `message` is not stable, and only `code` is what clients branch on. Per-error extras ride as untyped top-level keys. RFC 9457 defines a standard shape (`type`, `title`, `status`, `detail`, `instance`, plus extension members) and media type (`application/problem+json`) for exactly this purpose.

No client SDKs exist yet, so the migration is local to the server and the specs.

## Decision

Every HTTP error response across the API renders as RFC 9457 problem-details. 2xx responses are unaffected.

**Field mapping.** The existing envelope is *adapted* into RFC slots, not carried alongside:

- `error` is dropped — HTTP `status` is the category.
- `code` is the leaf of `type` (`https://novamoc.example/problems/<code>`). Clients branch on the leaf.
- `message` → `detail`.
- New `title` — short, fixed string per code (RFC §3.1).
- New `instance` — `urn:uuid:<uuid4>` per occurrence, for log correlation.
- Per-error extras stay as top-level keys, formally RFC §3.2 extension members.

**Rendering.** Litestar's `ProblemDetailsPlugin` is registered at the app level with `enable_for_all_http_exceptions=True` and an `exception_to_problem_detail_map`. Typed domain exceptions (today `SchemaCommandError`; in future, peers) stay framework-agnostic and are converted at the API edge. Adding an endpoint with a new exception class means one row in the map.

## Consequences

`Content-Type` flips from `application/json` to `application/problem+json` for every 4xx/5xx. OpenAPI regenerates accordingly.

Clients parse the leaf of `type` instead of branching on a top-level `code`. The codes themselves are the stable contract; the URI host is opaque per RFC 9457 §3.1 and can change without breaking clients.

Future endpoints inherit the rendering layer. New typed exceptions register a converter — there are no per-endpoint exception handlers.

The category field `error` (`invalid_request | conflict | not_found`) is gone. If telemetry needs the category, it derives from HTTP status.
```

- [ ] **Step 2: Lint pass on the ADR (link/Markdown sanity)**

Run: `ls docs/adr/016-rfc9457-problem-details-error-envelope.md`
Expected: file exists.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/016-rfc9457-problem-details-error-envelope.md
git commit -m "docs(adr): adopt RFC 9457 problem-details for API errors

ADR-016. Recorded before implementation lands so subsequent commits
can cite the decision (issue #8)."
```

---

## Task 2: Add `title` and `type_uri` to `SchemaCommandError`

**Files:**
- Modify: `src/py/novamoc/domain/schema/_errors.py`
- Test: `tests/schema/test_errors.py` (create if absent)

- [ ] **Step 1: Verify whether `tests/schema/test_errors.py` exists**

Run: `ls tests/schema/test_errors.py`
If absent: create the file with `from __future__ import annotations` and a single empty line. If present: read it before editing.

- [ ] **Step 2: Write the failing tests**

Add to `tests/schema/test_errors.py`:

```python
from __future__ import annotations

from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PROBLEM_TYPE_BASE,
    PayloadShapeError,
    SchemaCommandError,
)


def test_problem_type_base_is_stable_https_uri() -> None:
    assert PROBLEM_TYPE_BASE == "https://novamoc.example/problems"


def test_every_error_code_has_a_title() -> None:
    for code in ErrorCode:
        exc = SchemaCommandError(code=code)
        assert exc.title, f"missing title for {code!r}"


def test_type_uri_is_problem_base_plus_code() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    assert exc.type_uri == "https://novamoc.example/problems/name_reserved"


def test_subclass_status_codes_unchanged() -> None:
    assert PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES).status_code == 400
    assert ConflictError(code=ErrorCode.NAME_RESERVED).status_code == 409
    assert EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND).status_code == 404


def test_extras_still_carried() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    assert exc.extras == {"name": "Truck"}
```

- [ ] **Step 3: Run tests and verify they fail**

Run: `uv run pytest tests/schema/test_errors.py -v`
Expected: ImportError on `PROBLEM_TYPE_BASE` (and AttributeError on `title` / `type_uri`).

- [ ] **Step 4: Implement the changes in `_errors.py`**

This is an additive change — `error` and the existing constructor stay so the controller's three handlers (still in place after this task) continue to work. Task 6 removes `error` and the handlers in one cutover.

Replace `src/py/novamoc/domain/schema/_errors.py` with:

```python
"""Typed exceptions raised by schema-command handlers.

The app-level ``ProblemDetailsPlugin`` (see ``novamoc.asgi``) converts any
``SchemaCommandError`` into an ``application/problem+json`` response per
RFC 9457. ``msgspec.ValidationError`` and Litestar's ``ValidationException``
are mapped through the same plugin to a 400 problem-details with code
``invalid_payload_shape``.

The ``type`` URI's leaf segment is the stable code clients branch on.
``title`` is a short, fixed string per code (RFC 9457 §3.1).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


PROBLEM_TYPE_BASE = "https://novamoc.example/problems"


class ErrorCode(StrEnum):
    # 400 (request shape)
    PAYLOAD_NO_CHANGES = "payload_no_changes"
    INVALID_PAYLOAD_SHAPE = "invalid_payload_shape"
    # 409 (request well-shaped, conflicts with current projection state)
    NAME_RESERVED = "name_reserved"
    PARENT_TYPE_NOT_FOUND = "parent_type_not_found"
    # 404
    ENTITY_NOT_FOUND = "entity_not_found"


_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Update payload contained no changes.",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Request payload did not match the expected shape.",
    ErrorCode.NAME_RESERVED: "Name is already in use by another entity.",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type does not exist.",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found.",
}


_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
}


class SchemaCommandError(Exception):
    """Base class for schema-command failures.

    Subclasses pin ``status_code``. ``code`` is the failure mode within
    a category and is what clients branch on (via the leaf segment of
    ``type_uri``).
    """

    status_code: int = 400
    # Removed in Task 6 once the controller's legacy renderer is gone.
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

    @property
    def title(self) -> str:
        return _TITLES[self.code]

    @property
    def type_uri(self) -> str:
        return f"{PROBLEM_TYPE_BASE}/{self.code.value}"


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

- [ ] **Step 5: Run the full test suite — everything should still pass**

Run: `uv run pytest`
Expected: every existing test still PASSes. The change is additive: `error`, `code`, `message`, `extras`, and the constructor signature are unchanged; we only added `title` / `type_uri` properties and `_TITLES` / `PROBLEM_TYPE_BASE`.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/schema/_errors.py tests/schema/test_errors.py
git commit -m "feat(errors): add title and type_uri to SchemaCommandError

Per RFC 9457 problem-details migration (issue #8). The type URI is
\`{PROBLEM_TYPE_BASE}/{code}\` and the title is a short fixed string
per code. \`error\` is kept on the class for now; Task 6 removes it
when the controller-level legacy renderer is replaced."
```

---

## Task 3: Define `ProblemDetails` msgspec struct in new `api` package

**Files:**
- Create: `src/py/novamoc/api/__init__.py`
- Create: `src/py/novamoc/api/_problem_details.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_problem_details.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/__init__.py` (empty file).

Create `tests/api/test_problem_details.py`:

```python
from __future__ import annotations

import msgspec

from novamoc.api._problem_details import ProblemDetails


def test_problem_details_minimal_encode() -> None:
    pd = ProblemDetails(
        type="https://novamoc.example/problems/name_reserved",
        title="Name reserved",
        status=409,
        detail="Name is already in use by another entity.",
        instance="urn:uuid:01JABC...",
    )
    encoded = msgspec.json.decode(msgspec.json.encode(pd))
    assert encoded == {
        "type": "https://novamoc.example/problems/name_reserved",
        "title": "Name reserved",
        "status": 409,
        "detail": "Name is already in use by another entity.",
        "instance": "urn:uuid:01JABC...",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: ImportError on `novamoc.api._problem_details` (module does not exist).

- [ ] **Step 3: Create `src/py/novamoc/api/__init__.py`**

```python
"""API-layer types and helpers shared across HTTP/WebSocket endpoints.

This package holds transport-flavored concerns (problem-details rendering,
common envelopes, OpenAPI helpers) that are not domain logic but are also
not specific to a single endpoint.
"""
```

- [ ] **Step 4: Create `src/py/novamoc/api/_problem_details.py` with the struct only**

```python
"""RFC 9457 problem-details rendering for the whole API.

The `ProblemDetails` msgspec struct is published as the OpenAPI response
body for every error path. The converters below turn typed exceptions
(`SchemaCommandError`, msgspec/Litestar validation errors, eventually
others) into Litestar's `ProblemDetailsException`, which the
`ProblemDetailsPlugin` renders as `application/problem+json`.

Wire shape:
- `type` — opaque URI; clients branch on its leaf segment (the code).
- `title` — short, fixed string per code.
- `status` — HTTP status code, also on the response line.
- `detail` — human-readable message; not stable, do not branch on it.
- `instance` — `urn:uuid:<uuid4>` per occurrence, for log correlation.

Per-error-code extras (e.g., the conflicting `name`) are RFC 9457 §3.2
extension members — top-level keys alongside the standard slots.
"""

from __future__ import annotations

import uuid
from typing import Any

import msgspec


class ProblemDetails(msgspec.Struct, omit_defaults=True):
    """OpenAPI shape for an `application/problem+json` body.

    The struct only documents the standard RFC 9457 slots; per-error
    extension members are surfaced through Litestar's `extra` mapping
    on `ProblemDetailsException` and rendered as additional top-level
    keys (consumers ignore unknown fields).
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str


def make_instance() -> str:
    """Return an opaque per-occurrence instance identifier (`urn:uuid:<uuid4>`)."""

    return f"urn:uuid:{uuid.uuid4()}"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/api tests/api
git commit -m "feat(api): add ProblemDetails msgspec struct and api package

Scaffolds the api package and the OpenAPI shape for RFC 9457 error
responses (issue #8). Converters land in the next commit."
```

---

## Task 4: Converter for `SchemaCommandError`

**Files:**
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `tests/api/test_problem_details.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_problem_details.py`:

```python
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.api._problem_details import schema_command_error_to_problem_details
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)


def test_schema_command_error_conflict_renders_409_with_extras() -> None:
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    pd_exc = schema_command_error_to_problem_details(exc)

    assert isinstance(pd_exc, ProblemDetailsException)
    assert pd_exc.status_code == 409
    assert pd_exc.type_ == "https://novamoc.example/problems/name_reserved"
    assert pd_exc.title == "Name reserved"
    assert pd_exc.detail == "Name is already in use by another entity."
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")
    assert pd_exc.extra == {"name": "Truck"}


def test_schema_command_error_payload_shape_renders_400() -> None:
    exc = PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    pd_exc = schema_command_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "https://novamoc.example/problems/payload_no_changes"


def test_schema_command_error_entity_not_found_renders_404() -> None:
    exc = EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    pd_exc = schema_command_error_to_problem_details(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "https://novamoc.example/problems/entity_not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: ImportError on `schema_command_error_to_problem_details`.

- [ ] **Step 3: Implement the converter**

Append to `src/py/novamoc/api/_problem_details.py`:

```python
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.domain.schema._errors import SchemaCommandError


def schema_command_error_to_problem_details(
    exc: SchemaCommandError,
) -> ProblemDetailsException:
    """Convert a `SchemaCommandError` to a `ProblemDetailsException`.

    The plugin's response renderer flattens `extra` into top-level keys
    when it is a Mapping (RFC 9457 §3.2 extension members).
    """

    return ProblemDetailsException(
        type_=exc.type_uri,
        title=exc.title,
        status_code=exc.status_code,
        detail=exc.message,
        instance=make_instance(),
        extra=dict(exc.extras) if exc.extras else None,
    )
```

(Move the new `from litestar...` and `from novamoc.domain.schema...` imports to the top of the file alongside the existing imports — keep the file's import block tidy.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/api/_problem_details.py tests/api/test_problem_details.py
git commit -m "feat(api): convert SchemaCommandError to ProblemDetailsException"
```

---

## Task 5: Converters for msgspec and Litestar validation errors

**Files:**
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `tests/api/test_problem_details.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_problem_details.py`:

```python
import msgspec
from litestar.exceptions import ValidationException

from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
)


def test_msgspec_validation_error_renders_400_invalid_payload_shape() -> None:
    exc = msgspec.ValidationError("expected str, got int")
    pd_exc = msgspec_validation_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "https://novamoc.example/problems/invalid_payload_shape"
    assert pd_exc.title == "Invalid payload shape"
    assert "expected str, got int" in pd_exc.detail
    assert pd_exc.instance is not None and pd_exc.instance.startswith("urn:uuid:")


def test_litestar_validation_exception_renders_400_invalid_payload_shape() -> None:
    exc = ValidationException(detail="malformed body")
    pd_exc = litestar_validation_error_to_problem_details(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "https://novamoc.example/problems/invalid_payload_shape"
    assert pd_exc.title == "Invalid payload shape"
    assert pd_exc.detail == "malformed body"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: ImportError on the two converter names.

- [ ] **Step 3: Implement the converters**

Append to `src/py/novamoc/api/_problem_details.py`:

```python
import msgspec
from litestar.exceptions import ValidationException

from novamoc.domain.schema._errors import (
    ErrorCode,
    PROBLEM_TYPE_BASE,
    _TITLES,
)


def _invalid_payload_shape(detail: str) -> ProblemDetailsException:
    code = ErrorCode.INVALID_PAYLOAD_SHAPE
    return ProblemDetailsException(
        type_=f"{PROBLEM_TYPE_BASE}/{code.value}",
        title=_TITLES[code],
        status_code=400,
        detail=detail,
        instance=make_instance(),
    )


def msgspec_validation_error_to_problem_details(
    exc: msgspec.ValidationError,
) -> ProblemDetailsException:
    return _invalid_payload_shape(str(exc))


def litestar_validation_error_to_problem_details(
    exc: ValidationException,
) -> ProblemDetailsException:
    return _invalid_payload_shape(exc.detail or str(exc))
```

(Consolidate the imports at the top of the module; keep `_TITLES` import private — it lives next to `ErrorCode`. The leading underscore on `_TITLES` is fine across modules within the same project.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/api/test_problem_details.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/api/_problem_details.py tests/api/test_problem_details.py
git commit -m "feat(api): convert msgspec/Litestar validation errors to ProblemDetailsException"
```

---

## Task 6: Wire `ProblemDetailsPlugin` into the app and remove controller handlers

This is the cutover. After this task the wire format changes and the e2e tests need updating (Task 7).

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update `asgi.py` to register the plugin**

Replace `src/py/novamoc/asgi.py` with:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar


def create_app() -> Litestar:
    """Create the ASGI app."""

    import msgspec
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.exceptions import ValidationException
    from litestar.openapi.config import OpenAPIConfig
    from litestar.plugins.problem_details import (
        ProblemDetailsConfig,
        ProblemDetailsPlugin,
    )
    from litestar_granian import GranianPlugin

    from novamoc.api._problem_details import (
        litestar_validation_error_to_problem_details,
        msgspec_validation_error_to_problem_details,
        schema_command_error_to_problem_details,
    )
    from novamoc.domain.schema._errors import SchemaCommandError
    from novamoc.domain.schema.controllers import SchemaController

    session_config = AsyncSessionConfig(expire_on_commit=False)
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///test.sqlite",
        before_send_handler="autocommit",
        session_config=session_config,
        create_all=True,
    )

    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={
            SchemaCommandError: schema_command_error_to_problem_details,
            msgspec.ValidationError: msgspec_validation_error_to_problem_details,
            ValidationException: litestar_validation_error_to_problem_details,
        },
    )

    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            GranianPlugin(),
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

- [ ] **Step 2: Strip the three handlers and the `exception_handlers` mapping from `SchemaController`**

Replace `src/py/novamoc/domain/schema/controllers/_schema.py` with:

```python
"""HTTP controller for ``POST /schema``.

The route's request body is the discriminated union :data:`_payloads.SchemaRequest`,
so Litestar publishes a ``oneOf`` discriminated by ``type`` in the
OpenAPI schema. Dispatch is by the runtime variant class via
:func:`dispatch`.

Error rendering is the app-level ``ProblemDetailsPlugin`` registered in
``novamoc.asgi.create_app``: ``SchemaCommandError``,
``msgspec.ValidationError``, and Litestar's ``ValidationException`` all
render as ``application/problem+json`` per RFC 9457. The controller does
not register exception handlers itself.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, post
from litestar.openapi.datastructures import ResponseSpec

from novamoc.api._problem_details import ProblemDetails
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._dispatch import dispatch
from novamoc.domain.schema import _payloads, services as _services


class SchemaController(Controller):
    path = "/schema"
    tags = ["schema"]

    dependencies = (
        providers.create_service_dependencies(_services.AssetTypeService, "asset_type_service")
        | providers.create_service_dependencies(
            _services.AssetTypeFieldService, "asset_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeService, "maintenance_record_type_service",
        )
        | providers.create_service_dependencies(
            _services.MaintenanceRecordTypeFieldService, "maintenance_record_type_field_service",
        )
        | providers.create_service_dependencies(
            _services.SchemaChangeLogService, "schema_change_log_service",
        )
    )

    @post(
        "/",
        responses={
            400: ResponseSpec(ProblemDetails, description="Invalid request"),
            404: ResponseSpec(ProblemDetails, description="Entity not found"),
            409: ResponseSpec(ProblemDetails, description="Conflict"),
        },
    )
    async def post(
        self,
        data: _payloads.SchemaRequest,
        asset_type_service: _services.AssetTypeService,
        asset_type_field_service: _services.AssetTypeFieldService,
        maintenance_record_type_service: _services.MaintenanceRecordTypeService,
        maintenance_record_type_field_service: _services.MaintenanceRecordTypeFieldService,
        schema_change_log_service: _services.SchemaChangeLogService,
    ) -> _payloads.SchemaResponse:
        services = ServiceBundle(
            asset_type=asset_type_service,
            asset_type_field=asset_type_field_service,
            maintenance_record_type=maintenance_record_type_service,
            maintenance_record_type_field=maintenance_record_type_field_service,
            change_log=schema_change_log_service,
        )
        outcome = await dispatch(services, data)
        return _payloads.SchemaResponse(
            schema_version=outcome.schema_version,
            entity_id=outcome.entity_id,
            outcome=outcome.outcome.value,
            committed_at=outcome.committed_at,
        )
```

- [ ] **Step 3: Remove the `error` class attribute from `SchemaCommandError`**

Edit `src/py/novamoc/domain/schema/_errors.py`:

Delete the line `    error: str = "invalid_request"` from `SchemaCommandError`, and delete the lines `    error = "invalid_request"`, `    error = "conflict"`, `    error = "not_found"` from the three subclasses. Also delete the `# Removed in Task 6 once...` comment.

The class attribute is unused now that the controller-level renderer is gone. The category that used to live in `error` is now (a) implicit in HTTP `status` and (b) the leaf of `type_uri`.

- [ ] **Step 4: Update `tests/conftest.py` `app` fixture to include the plugin**

Add these imports to the top-level imports of `tests/conftest.py`:

```python
import msgspec
from litestar.exceptions import ValidationException
from litestar.plugins.problem_details import (
    ProblemDetailsConfig,
    ProblemDetailsPlugin,
)

from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_command_error_to_problem_details,
)
from novamoc.domain.schema._errors import SchemaCommandError
```

Then replace the body of the `app` fixture so the plugin is registered:

```python
@pytest.fixture
async def app() -> Litestar:
    """A Litestar app with an in-memory shared-cache SQLite for e2e tests.

    ``cache=shared`` lets multiple connections within the same process
    reach the same in-memory db, which the plugin needs because it opens
    its own engine.
    """
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///file::memory:?cache=shared&uri=true",
        before_send_handler="autocommit",
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=True,
    )
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={
            SchemaCommandError: schema_command_error_to_problem_details,
            msgspec.ValidationError: msgspec_validation_error_to_problem_details,
            ValidationException: litestar_validation_error_to_problem_details,
        },
    )
    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

- [ ] **Step 5: Run the full test suite — e2e tests will now FAIL on shape**

Run: `uv run pytest`
Expected: handler-level tests, payload tests, and unit tests PASS. The e2e tests (`tests/schema/test_endpoint_e2e.py` and `tests/schema/test_app_wiring.py`) FAIL because they assert on the old envelope (`body["error"] == "conflict"`, etc.). This is the intended state — Task 7 fixes them.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 7: Commit (red e2e tests included)**

This commit moves rendering to the plugin but breaks the e2e shape assertions. Ordinarily we want green commits; here the next task is small and tightly scoped, so a temporary red on e2e is acceptable.

If you prefer a green tree, fold Tasks 6 and 7 into one commit by skipping this commit and going straight to Task 7, then committing both together at the end of Task 7.

```bash
git add src/py/novamoc/asgi.py \
        src/py/novamoc/domain/schema/controllers/_schema.py \
        src/py/novamoc/domain/schema/_errors.py \
        tests/conftest.py
git commit -m "feat(api): wire ProblemDetailsPlugin at app level

Removes the three controller-scoped exception handlers in favor of a
single app-level rendering layer. E2E tests fail on the new envelope
shape — Task 7 updates them."
```

---

## Task 7: Update e2e tests for the new envelope and content-type

**Files:**
- Modify: `tests/schema/test_endpoint_e2e.py`
- Modify: `tests/schema/test_app_wiring.py`
- Modify: `tests/schema/test_payloads.py`
- Modify: `src/py/novamoc/domain/schema/_payloads.py`

- [ ] **Step 1: Rewrite the e2e error-shape assertions in `test_endpoint_e2e.py`**

Update the failure assertions to match the new shape. Replace these blocks:

```python
# In test_post_schema_returns_409_on_duplicate_name
    assert second.status_code == 409
    err = second.json()
    assert err["error"] == "conflict"
    assert err["code"] == "name_reserved"
```

with:

```python
# In test_post_schema_returns_409_on_duplicate_name
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    err = second.json()
    assert err["status"] == 409
    assert err["type"] == "https://novamoc.example/problems/name_reserved"
    assert err["title"] == "Name reserved"
```

Replace:

```python
# In test_post_schema_returns_404_for_update_missing
    assert resp.status_code == 404
    assert resp.json()["code"] == "entity_not_found"
```

with:

```python
# In test_post_schema_returns_404_for_update_missing
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["type"] == "https://novamoc.example/problems/entity_not_found"
```

Replace:

```python
# In test_post_schema_returns_400_on_unknown_command
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_payload_shape"
```

with:

```python
# In test_post_schema_returns_400_on_unknown_command
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == "https://novamoc.example/problems/invalid_payload_shape"
```

Replace:

```python
# In test_post_schema_returns_400_on_payload_with_unknown_field
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "invalid_request"
    assert body["code"] == "invalid_payload_shape"
```

with:

```python
# In test_post_schema_returns_400_on_payload_with_unknown_field
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "https://novamoc.example/problems/invalid_payload_shape"
```

The success-path assertions (`test_post_schema_creates_asset_type` and the success leg of `test_rollback_on_4xx_does_not_append_change_log`) are unchanged — 2xx responses still use `application/json`.

- [ ] **Step 2: Update `tests/schema/test_app_wiring.py`**

Replace lines 13–16 with:

```python
        assert resp.status_code == 400, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["type"] == "https://novamoc.example/problems/invalid_payload_shape"
        assert body["status"] == 400
```

- [ ] **Step 3: Drop the now-stale `SchemaErrorResponse` test**

Remove `test_schema_error_response_minimal_envelope` (the function spanning roughly lines 327–331 of `tests/schema/test_payloads.py`). Also drop the `_payloads.SchemaErrorResponse` import from that file if it is now unused.

- [ ] **Step 4: Drop `SchemaErrorResponse` from `src/py/novamoc/domain/schema/_payloads.py`**

Delete the lines:

```python
class SchemaErrorResponse(msgspec.Struct, omit_defaults=True):
    error: str  # "invalid_request" | "conflict" | "not_found"
    code: str
    message: str
```

(plus the preceding blank-line/comment block).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: all tests PASS.

- [ ] **Step 6: Add a new e2e assertion for extension-member rendering**

Append to `tests/schema/test_endpoint_e2e.py`:

```python
async def test_post_schema_problem_includes_instance_and_extras(client) -> None:
    """RFC 9457 §3.2 extension members are rendered as top-level keys, and
    each occurrence carries an opaque `instance` URI for log correlation."""

    name = f"WithExtras-{uuid4()}"
    body = {
        "type": "create_asset_type",
        "tenant_id": _T,
        "entity_id": str(uuid4()),
        "payload": {"name": name},
    }
    first = await client.post("/schema", json=body)
    assert first.status_code in (200, 201)
    body["entity_id"] = str(uuid4())
    second = await client.post("/schema", json=body)
    assert second.status_code == 409
    err = second.json()
    # Extension member surfaced from `extras={"name": "..."}`.
    assert err["name"] == name
    # Per-occurrence instance.
    assert err["instance"].startswith("urn:uuid:")
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/schema/test_endpoint_e2e.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 8: Lint and type-check**

Run: `uv run ruff check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add tests/schema/test_endpoint_e2e.py \
        tests/schema/test_app_wiring.py \
        tests/schema/test_payloads.py \
        src/py/novamoc/domain/schema/_payloads.py
git commit -m "test(api): assert RFC 9457 problem-details envelope on errors

Drops the legacy SchemaErrorResponse struct now that the controller's
OpenAPI references novamoc.api._problem_details.ProblemDetails."
```

---

## Task 8: Document the new contract

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-05-01-schema-endpoint-design.md`
- Modify: `docs/adr/013-http-and-websocket-transports.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Find the paragraph in the "Schema endpoint" section that begins with "**Controller** — `controllers/_schema.py::SchemaController` mounts at `/schema`, wires service DI..." and replace its description of the three exception handlers and the `{error, code, message, ...extras}` envelope with:

> **Controller** — `controllers/_schema.py::SchemaController` mounts at `/schema` and wires service DI via `advanced_alchemy.extensions.litestar.providers.create_service_dependencies`. Error rendering is the app-level `ProblemDetailsPlugin` registered in `asgi.create_app`: `SchemaCommandError`, `msgspec.ValidationError`, and Litestar's `ValidationException` all render as `application/problem+json` per ADR-016. The OpenAPI doc moves to `/openapi` because the route owns `/schema`.

Then update the "Errors are raised as typed `SchemaCommandError` subclasses..." paragraph to:

> Errors are raised as typed `SchemaCommandError` subclasses (`PayloadShapeError`, `ConflictError`, `EntityNotFoundError`) carrying an `ErrorCode` enum value (`name_reserved`, `parent_type_not_found`, `entity_not_found`, `payload_no_changes`, `invalid_payload_shape`). `status_code` is pinned by the subclass; the leaf segment of `type_uri` (= the code value) is what clients branch on. Per-error extras (`name`, `field`, ...) ride as top-level extension members per ADR-016.

- [ ] **Step 2: Update the schema-endpoint design spec**

Open `docs/superpowers/specs/2026-05-01-schema-endpoint-design.md` and:

a. Bump the "Status" line: `Approved. Revised 2026-05-02 to record the msgspec untagged-union constraint, and again on 2026-05-02 to adopt the API-wide error envelope from ADR-016`.

b. Replace the entire **Errors** section (around line 321) with:

> ### Errors
>
> Typed exceptions: `SchemaCommandError` with `PayloadShapeError`, `ConflictError`, `EntityNotFoundError` subclasses pinning `status_code`, and an `ErrorCode` enum for stable identifiers. Rendering is the app-level layer described in ADR-016; the controller registers no exception handlers itself. Each `ErrorCode` has a fixed `title` and a stable `type` URI of the form `https://novamoc.example/problems/<code>`.

c. Replace the **Response envelopes** failure-example block with:

> Failure (409, `application/problem+json` per ADR-016):
> ```json
> {
>   "type": "https://novamoc.example/problems/name_reserved",
>   "title": "Name reserved",
>   "status": 409,
>   "detail": "Name is already in use by another entity.",
>   "instance": "urn:uuid:01958f3b-3b9f-7d3a-89aa-000000000001",
>   "name": "Truck"
> }
> ```
>
> Per-error extras (e.g., the conflicting `name` for `name_reserved`) ride as top-level keys; consumers ignore unknown fields.

- [ ] **Step 3: Update ADR-013**

Append a one-sentence cross-reference to `docs/adr/013-http-and-websocket-transports.md`, immediately after the **HTTP `/schema`.** subsection:

> **API-wide error envelope.** All HTTP error responses use the contract recorded in ADR-016.

- [ ] **Step 4: Run the full test suite once more**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md \
        docs/superpowers/specs/2026-05-01-schema-endpoint-design.md \
        docs/adr/013-http-and-websocket-transports.md
git commit -m "docs: align CLAUDE.md, schema-endpoint spec, and ADR-013 with ADR-016"
```

---

## Final verification

- [ ] **Step 1: Run the full test suite from a clean state**

Run: `uv run pytest -v`
Expected: every test PASSes; nothing is skipped without reason.

- [ ] **Step 2: Confirm OpenAPI references the new struct**

Run: `uv run python -c "from novamoc.asgi import create_app; import json; print(json.dumps(create_app().openapi_schema.to_schema(), indent=2))" | rg -n "ProblemDetails|application/problem"`

Expected: the schema mentions `ProblemDetails` in the route's `responses` and (via the plugin) records the `application/problem+json` content type for error responses.

- [ ] **Step 3: Sanity-check the live server**

Run (in one terminal): `just serve`

In another terminal:
```bash
curl -i -X POST http://127.0.0.1:8000/schema/ \
  -H 'Content-Type: application/json' \
  -d '{"type":"do_a_barrel_roll","tenant_id":"t","entity_id":"01958f3b-3b9f-7d3a-89aa-000000000001","payload":{}}'
```

Expected: HTTP/1.1 400, `Content-Type: application/problem+json`, body containing `type`, `title`, `status`, `detail`, `instance`.

- [ ] **Step 4: Push the branch (only if user confirms — see CLAUDE.md guidance)**

This is an API-wide contract change. Confirm with the user before pushing or opening a PR.
