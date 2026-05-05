# Tenant Resolution Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the design at `docs/superpowers/specs/2026-05-04-tenant-resolution-middleware-design.md` — an `ASGIMiddleware` that reads a hardcoded bearer token off `Authorization`, builds a `TenantContext`, stamps it on `request.state.tenant`, and feeds it into handlers via DI. Drop `tenant_id` from every `POST /schema` body and from the `GET /schema/{tenant_id}` URL path. Replace the URL-path-based 404 `tenant_not_found` with a credential-based 401 `tenant_not_resolved`. Land ADR-017 and supersede ADR-014 in lockstep.

**Architecture:** New `domain/accounts/` package with five modules: `_context.py` (TenantContext struct), `_resolver.py` (token → context, the swap point), `_middleware.py` (ASGIMiddleware subclass with `exclude_path_pattern = "^/openapi"`), `_di.py` (request → TenantContext), `_errors.py` (TenantResolutionError). The dispatch contract widens by one positional argument (`tenant: TenantContext`); 22 command handlers and one read handler bind against it. Errors flow through the existing `ProblemDetailsPlugin` via a new mapper registered alongside the schema mapper.

**Tech Stack:** Python 3.14, Litestar 2.21.1 (uses `ASGIMiddleware` from 2.15+), msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, pytest (asyncio auto mode), uv, ruff, ty.

---

## File map

**Created:**
- `src/py/novamoc/domain/accounts/__init__.py` — re-exports `TenantContext`, `TenantMiddleware`, `provide_tenant`, `resolve_tenant`, `TenantResolutionError`.
- `src/py/novamoc/domain/accounts/_context.py` — `TenantContext` frozen `msgspec.Struct`.
- `src/py/novamoc/domain/accounts/_resolver.py` — `_TENANT_T1_DEV_TOKEN` constant + `resolve_tenant(scope) -> TenantContext`.
- `src/py/novamoc/domain/accounts/_middleware.py` — `TenantMiddleware(ASGIMiddleware)` with the OpenAPI bypass.
- `src/py/novamoc/domain/accounts/_di.py` — `provide_tenant(request) -> TenantContext`.
- `src/py/novamoc/domain/accounts/_errors.py` — `TenantResolutionError(Exception)`.
- `tests/accounts/__init__.py`, `tests/accounts/test_context.py`, `tests/accounts/test_resolver.py`, `tests/accounts/test_middleware.py`, `tests/accounts/test_di.py` — unit tests.
- `docs/adr/017-tenant-resolution-from-the-request-envelope.md` — the new ADR.

**Modified:**
- `docs/adr/014-multi-tenancy-model.md` — `## Status` flips from `Accepted` to `Superseded by ADR-017`.
- `src/py/novamoc/asgi.py` — register `TenantMiddleware()` + `TenantResolutionError` mapper.
- `src/py/novamoc/api/_problem_details.py` — add `tenant_resolution_error_to_problem_details`; delete the `TENANT_NOT_FOUND` rows in `_TITLES` / `_STATUS_CODES`.
- `src/py/novamoc/config.py` — delete `KNOWN_TENANT_IDS`.
- `src/py/novamoc/domain/schema/_payloads.py` — drop `tenant_id: str` from all 22 command structs; add `forbid_unknown_fields=True` to `_SchemaCommand`.
- `src/py/novamoc/domain/schema/_bundle.py` — `Handler` alias gains `TenantContext`.
- `src/py/novamoc/domain/schema/_dispatch.py` — `dispatch(services, tenant, request)`.
- `src/py/novamoc/domain/schema/_handlers/asset_type.py`, `_handlers/asset_type_field.py`, `_handlers/maintenance_record_type.py`, `_handlers/maintenance_record_type_field.py` — handler signatures gain `tenant: TenantContext`; `req.tenant_id` references become `tenant.tenant_id`.
- `src/py/novamoc/domain/schema/controllers/_schema.py` — apply_command takes `tenant`; `read_snapshot` becomes `@get("/")`; deletes the `KNOWN_TENANT_IDS` check; `provide_tenant` registered in `dependencies`.
- `src/py/novamoc/domain/schema/_errors.py` — delete `ErrorCode.TENANT_NOT_FOUND`, its `_DEFAULT_MESSAGES` row, `TenantNotFoundError`.
- `tests/conftest.py` — register `TenantMiddleware` + new mapper on the `app` fixture; default the `client` fixture's headers to attach the dev bearer token; add a session-wide `tenant_context` fixture.
- `tests/schema/test_endpoint_e2e.py`, `tests/schema/test_read_endpoint_e2e.py`, `tests/schema/test_app_wiring.py`, `tests/schema/test_handlers_*.py` (×4), `tests/schema/test_payloads.py` — drop `tenant_id` from bodies, switch read URL from `/schema/{tenant_id}` to `/schema`, update handler test calls to the new signature.
- `tests/api/test_problem_details.py` — delete `test_schema_error_tenant_not_found_renders_404_with_extras`; add coverage for the new 401 mapper.
- `README.md` — note the dev bearer token under a "Development credentials" subsection.

---

## Conventions

- **TDD throughout.** Every behavioural task starts with a failing test. Watch the test fail before implementing.
- **No DB mocks.** All DB-touching tests use the real in-memory aiosqlite (per `tests/conftest.py`).
- **`uv run` everything.** Tests, lint, type-check all go through `uv run`.
- **`pytest` is in asyncio auto mode** — async tests do not need `@pytest.mark.asyncio`.
- **Frequent commits.** One commit per task; the working tree is left clean and tests passing at every commit boundary. Hooks are honoured (no `--no-verify`).
- **ADR-first.** Task 1 lands ADR-017 and the ADR-014 status flip before any code lands. The ADR is the decision record; the spec and plan are the working docs.
- **File-count heuristic.** The plan's quality bar caps at 8 files per task. Task 8 (plumbing TenantContext through the dispatch contract) intentionally exceeds this for a mechanical refactor across one conceptual seam; the rationale is recorded inline.

---

## Task 1: Land ADR-017 and flip ADR-014 to superseded

**Files:**
- Create: `docs/adr/017-tenant-resolution-from-the-request-envelope.md`
- Modify: `docs/adr/014-multi-tenancy-model.md`

The ADR is the decision record this PR sits on top of. Land it before code so reviewers reading commit history see the decision recorded before its implementation.

- [ ] **Step 1: Write ADR-017**

Create `docs/adr/017-tenant-resolution-from-the-request-envelope.md` using the post-template MADR shape (YAML frontmatter + `Context and Problem Statement` / `Decision Drivers` / `Considered Options` / `Decision Outcome` / `Consequences` / `Confirmation` / `More Information`). Required content:

- **Frontmatter:** `status: accepted`, `date: 2026-05-04`, `category: multi-tenancy`, decision-makers list per repo convention.
- **Context:** ADR-014 said "Until auth exists, the tenant_id is taken from the client's hello message." That deferral has hit its expiry — every API endpoint coming after the schema endpoints needs tenant scoping, and the body/path approach scales poorly. Issue #19 tracks the resulting `POST /schema` vs `GET /schema/{tenant_id}` asymmetry.
- **Decision drivers:** one source of truth for tenant identity; swap-friendliness for a future credential format; symmetry between read and write endpoints; observability of pre-auth limitations.
- **Considered options:** URL path parameter; body field; request envelope (header) resolved by middleware. List the chosen option first.
- **Decision outcome:** request envelope. v1: an `ASGIMiddleware` reads a bearer token off `Authorization`, matches it against a single hardcoded constant, builds a `TenantContext`, and stamps it onto `request.state.tenant`. The handler-facing type is `TenantContext` (frozen `msgspec.Struct`) so future fields (user id, scopes) extend the struct rather than the dispatch signature. Re-state the row-scoping decision verbatim from ADR-014 since the multi-tenancy story now lives here.
- **Consequences:** Good — symmetry between endpoints, dispatch contract stable across credential-format swaps, RFC 9457 401 wire shape consistent with other failure modes. Bad — single hardcoded token has no rotation/expiry/revocation; bypass list is hardcoded.
- **Confirmation:** the unit tests in `tests/accounts/test_resolver.py` pin the resolver's accept/reject behaviour, and the e2e tests pin the wire contract. The `forbid_unknown_fields=True` on `_SchemaCommand` ensures any client still sending `tenant_id` in the body fails loud.
- **More information:** cite ADR-014 (superseded by this), ADR-008 (the schema endpoint), ADR-016 (problem-details). Link to issue #19 (closed by this ADR) and the design spec at `docs/superpowers/specs/2026-05-04-tenant-resolution-middleware-design.md`.

- [ ] **Step 2: Update ADR-014's status to superseded**

In `docs/adr/014-multi-tenancy-model.md`, change:

```
## Status

Accepted
```

to:

```
## Status

Superseded by ADR-017
```

Do not edit the body of ADR-014 — the row-scoping decision survives intact, just rehoused in ADR-017. Per ADR-000's rules, accepted ADRs are not edited except for status changes.

- [ ] **Step 3: Lint check on the ADR file**

```bash
ls docs/adr/017-tenant-resolution-from-the-request-envelope.md
```

(Sanity check — no automated linter for the markdown beyond `ruff`'s scope.)

- [ ] **Step 4: Run the test suite to confirm nothing regressed**

```bash
uv run pytest
```

Expected: same baseline as pre-task (no code changed).

- [ ] **Step 5: Commit**

```bash
git add docs/adr/017-tenant-resolution-from-the-request-envelope.md docs/adr/014-multi-tenancy-model.md
git commit -m "docs(adr): ADR-017 tenant resolution from the request envelope; supersede ADR-014"
```

---

## Task 2: Accounts package + `TenantContext`

**Files:**
- Create: `src/py/novamoc/domain/accounts/__init__.py`
- Create: `src/py/novamoc/domain/accounts/_context.py`
- Create: `tests/accounts/__init__.py`
- Create: `tests/accounts/test_context.py`

The struct is the type every handler will eventually see. Land it first so subsequent tasks have a concrete dependency.

- [ ] **Step 1: Write the failing test**

Create `tests/accounts/__init__.py` (empty) and `tests/accounts/test_context.py`:

```python
from __future__ import annotations

import pytest

from novamoc.domain.accounts import TenantContext


def test_tenant_context_holds_tenant_id() -> None:
    ctx = TenantContext(tenant_id="t1")
    assert ctx.tenant_id == "t1"


def test_tenant_context_is_frozen() -> None:
    ctx = TenantContext(tenant_id="t1")
    with pytest.raises(AttributeError):
        ctx.tenant_id = "t2"  # ty: ignore[unresolved-attribute]


def test_tenant_context_equality_is_value_based() -> None:
    assert TenantContext(tenant_id="t1") == TenantContext(tenant_id="t1")
    assert TenantContext(tenant_id="t1") != TenantContext(tenant_id="t2")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/accounts/test_context.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novamoc.domain.accounts'`.

- [ ] **Step 3: Create the package and the struct**

Create `src/py/novamoc/domain/accounts/_context.py`:

```python
"""Per-request tenant context.

Produced by the resolver, stamped on ``scope["state"]["tenant"]`` by
``TenantMiddleware``, and handed to handlers via the ``provide_tenant``
DI provider. v1 carries only the tenant id; future fields (user id,
scopes, actor kind) extend this struct so the dispatch contract stays
stable across credential-format swaps.
"""

from __future__ import annotations

import msgspec


class TenantContext(msgspec.Struct, frozen=True):
    tenant_id: str
```

Create `src/py/novamoc/domain/accounts/__init__.py`:

```python
"""Tenant resolution from the request envelope (ADR-017).

This package owns: the per-request ``TenantContext``, the ``resolve_tenant``
function (the credential-shape swap point), the ``TenantMiddleware`` that
calls it, the ``provide_tenant`` DI provider, and the
``TenantResolutionError`` raised on resolution failure.
"""

from __future__ import annotations

from novamoc.domain.accounts._context import TenantContext

__all__ = ("TenantContext",)
```

(The `__init__.py` will gain more re-exports as later tasks add modules.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/accounts/test_context.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/accounts/ tests/accounts/
git commit -m "feat(accounts): TenantContext frozen msgspec.Struct"
```

---

## Task 3: `TenantResolutionError` + 401 problem-details mapper

**Files:**
- Create: `src/py/novamoc/domain/accounts/_errors.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `tests/api/test_problem_details.py`

The mapper exists before the middleware so the middleware's exception path has somewhere to land in tasks 5 and 7.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_problem_details.py`:

```python
def test_tenant_resolution_error_renders_401() -> None:
    from novamoc.api._problem_details import (
        tenant_resolution_error_to_problem_details,
    )
    from novamoc.domain.accounts import TenantResolutionError

    exc = TenantResolutionError()
    pd_exc = tenant_resolution_error_to_problem_details(exc)

    assert pd_exc.status_code == 401
    assert pd_exc.type_ == "urn:novamoc:problems:tenant_not_resolved"
    assert pd_exc.title == "Tenant not resolved"
    assert pd_exc.extra is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/api/test_problem_details.py::test_tenant_resolution_error_renders_401 -v
```

Expected: FAIL with `ImportError: cannot import name 'TenantResolutionError'`.

- [ ] **Step 3: Implement the exception**

Create `src/py/novamoc/domain/accounts/_errors.py`:

```python
"""Typed exceptions raised by tenant resolution.

Today the only failure mode is "credential is missing or unrecognized" —
v1 maps every variant (no header, wrong scheme, wrong token) to a single
``TenantResolutionError``. When token formats grow, additional codes can
split out (``token_expired``, ``token_revoked``, ...); v1 keeps it to one
so client code does not branch on dev-period internals.
"""

from __future__ import annotations


class TenantResolutionError(Exception):
    """Raised when the request envelope did not carry a recognized credential."""

    def __init__(self, message: str = "Tenant could not be resolved from request.") -> None:
        super().__init__(message)
        self.message = message
```

Update `src/py/novamoc/domain/accounts/__init__.py`:

```python
from novamoc.domain.accounts._context import TenantContext
from novamoc.domain.accounts._errors import TenantResolutionError

__all__ = ("TenantContext", "TenantResolutionError")
```

- [ ] **Step 4: Implement the mapper**

Edit `src/py/novamoc/api/_problem_details.py`. Add the import:

```python
from novamoc.domain.accounts import TenantResolutionError
```

Append the mapper function below `schema_error_to_problem_details`:

```python
def tenant_resolution_error_to_problem_details(
    exc: TenantResolutionError,
) -> ProblemDetailsException:
    """Convert a ``TenantResolutionError`` to a 401 ``ProblemDetailsException``.

    The wire shape is intentionally minimal: ``extras`` is empty so client
    code does not branch on which variant of the credential failure was
    triggered. When token formats grow, additional codes split out and
    extras can carry per-code context.
    """

    return ProblemDetailsException(
        type_=f"{_PROBLEM_TYPE_BASE}:tenant_not_resolved",
        title="Tenant not resolved",
        status_code=401,
        detail=exc.message,
        instance=make_instance(),
    )
```

(Use `_PROBLEM_TYPE_BASE` from the same module — the constant already exists. The 401 is hardcoded because there's only one tenant-resolution failure mode in v1; promoting it into `_STATUS_CODES` would require an `ErrorCode` member in the schema enum, which the spec deliberately avoids.)

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/api/test_problem_details.py::test_tenant_resolution_error_renders_401 -v
```

Expected: PASS.

- [ ] **Step 6: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/accounts/ src/py/novamoc/api/_problem_details.py tests/api/test_problem_details.py
git commit -m "feat(accounts): TenantResolutionError + 401 problem-details mapper"
```

---

## Task 4: `resolve_tenant` function + unit tests

**Files:**
- Create: `src/py/novamoc/domain/accounts/_resolver.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Create: `tests/accounts/test_resolver.py`

The resolver is the swap point. Its accept/reject behaviour is what every wire-level rejection test eventually anchors against.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_resolver.py`:

```python
from __future__ import annotations

import pytest

from novamoc.domain.accounts import TenantContext, TenantResolutionError


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    """Minimal HTTP ASGI scope sufficient for the resolver."""
    return {"type": "http", "headers": headers or []}


def test_valid_bearer_returns_t1_context() -> None:
    from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN, resolve_tenant

    scope = _scope([(b"authorization", f"Bearer {_TENANT_T1_DEV_TOKEN}".encode())])
    assert resolve_tenant(scope) == TenantContext(tenant_id="t1")


def test_missing_authorization_header_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    with pytest.raises(TenantResolutionError):
        resolve_tenant(_scope())


def test_wrong_scheme_raises() -> None:
    from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN, resolve_tenant

    for scheme in (b"Basic", b"Token", b"bearer"):  # case-sensitive per RFC 6750
        scope = _scope([(b"authorization", scheme + b" " + _TENANT_T1_DEV_TOKEN.encode())])
        with pytest.raises(TenantResolutionError):
            resolve_tenant(scope)


def test_wrong_token_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    scope = _scope([(b"authorization", b"Bearer not-the-real-token")])
    with pytest.raises(TenantResolutionError):
        resolve_tenant(scope)


def test_empty_token_raises() -> None:
    from novamoc.domain.accounts._resolver import resolve_tenant

    scope = _scope([(b"authorization", b"Bearer ")])
    with pytest.raises(TenantResolutionError):
        resolve_tenant(scope)


def test_authorization_value_with_extra_whitespace_raises() -> None:
    from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN, resolve_tenant

    # Tightest reasonable acceptance: exact "Bearer <single-token>" shape.
    scope = _scope([(b"authorization", f"Bearer  {_TENANT_T1_DEV_TOKEN}".encode())])
    with pytest.raises(TenantResolutionError):
        resolve_tenant(scope)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/accounts/test_resolver.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novamoc.domain.accounts._resolver'`.

- [ ] **Step 3: Implement the resolver**

Create `src/py/novamoc/domain/accounts/_resolver.py`:

```python
"""Tenant resolution from the request envelope.

v1: read the ``Authorization`` header off the ASGI scope, expect a
``Bearer <token>`` value, match the token against a single hardcoded
constant. On match return ``TenantContext(tenant_id="t1")``; on any
failure raise ``TenantResolutionError``.

This module is the swap point. The v2 resolver will look up the bearer
token in a tenant table (or external IdP) and build a richer context;
the middleware and DI layers do not change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.domain.accounts._context import TenantContext
from novamoc.domain.accounts._errors import TenantResolutionError

if TYPE_CHECKING:
    from litestar.types import Scope

# Development-only credential. Anyone with checkout access can read it; that is
# the trust model for the dev period (ADR-017). Replaced by a real per-tenant
# token registry — see issue #19.
_TENANT_T1_DEV_TOKEN = "t1-dev-token"
_BEARER_PREFIX = b"Bearer "


def resolve_tenant(scope: "Scope") -> TenantContext:
    """Return the ``TenantContext`` for this request, or raise.

    Raises:
        TenantResolutionError: when the ``Authorization`` header is missing,
            uses a non-Bearer scheme, or carries an unrecognized token.
    """
    headers = scope.get("headers", ())
    for name, value in headers:
        if name == b"authorization":
            if not value.startswith(_BEARER_PREFIX):
                raise TenantResolutionError()
            token = value[len(_BEARER_PREFIX) :]
            if token == _TENANT_T1_DEV_TOKEN.encode():
                return TenantContext(tenant_id="t1")
            raise TenantResolutionError()
    raise TenantResolutionError()
```

Update `src/py/novamoc/domain/accounts/__init__.py`:

```python
from novamoc.domain.accounts._context import TenantContext
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._resolver import resolve_tenant

__all__ = ("TenantContext", "TenantResolutionError", "resolve_tenant")
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/accounts/test_resolver.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/accounts/_resolver.py src/py/novamoc/domain/accounts/__init__.py tests/accounts/test_resolver.py
git commit -m "feat(accounts): resolve_tenant reads Bearer token from ASGI scope"
```

---

## Task 5: `TenantMiddleware` + unit tests (state, exception, bypass)

**Files:**
- Create: `src/py/novamoc/domain/accounts/_middleware.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Create: `tests/accounts/test_middleware.py`

The middleware is verified two ways: a unit test that calls `__call__` against a mock ASGI app (state set, exception raised), and an integration test that spins up a Litestar app with a probe handler and asserts both the success path and the bypass.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_middleware.py`:

```python
from __future__ import annotations

from litestar import Litestar, get
from litestar.testing import AsyncTestClient

from novamoc.domain.accounts import TenantContext
from novamoc.domain.accounts._middleware import TenantMiddleware
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN

_VALID_AUTH = {"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}


@get("/probe")
async def _probe(request) -> dict:
    return {"tenant_id": request.state.tenant.tenant_id}


@get("/openapi/probe-bypass")
async def _bypass_probe(request) -> dict:
    # Demonstrate the bypass: this handler runs without state["tenant"] when
    # exclude_path_pattern fires.
    has_tenant = hasattr(request.state, "tenant")
    return {"has_tenant": has_tenant}


def _app() -> Litestar:
    return Litestar(
        route_handlers=[_probe, _bypass_probe],
        middleware=[TenantMiddleware()],
    )


async def test_valid_bearer_sets_tenant_context_on_state() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/probe", headers=_VALID_AUTH)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"tenant_id": "t1"}


async def test_missing_bearer_yields_401_problem_details() -> None:
    # The middleware raises; without an exception_handler, Litestar renders
    # the default 500. To pin the 401 wire shape we need the
    # ProblemDetailsPlugin registered — that path is exercised by the
    # asgi.create_app integration test in Task 7. Here we just assert the
    # exception type propagates from handle().
    from novamoc.domain.accounts import TenantResolutionError

    raised = False
    try:
        async with AsyncTestClient(_app(), raise_server_exceptions=True) as client:
            await client.get("/probe")
    except TenantResolutionError:
        raised = True
    assert raised, "TenantResolutionError must propagate from middleware"


async def test_openapi_path_bypasses_resolution() -> None:
    async with AsyncTestClient(_app()) as client:
        # No Authorization header — the bypass exempts /openapi/* from the resolver.
        resp = await client.get("/openapi/probe-bypass")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"has_tenant": False}


async def test_middleware_writes_tenant_context_value() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/probe", headers=_VALID_AUTH)
        # Sanity: the value on state is exactly TenantContext(tenant_id="t1"),
        # not a dict or a bare string.
        assert resp.json() == {"tenant_id": TenantContext(tenant_id="t1").tenant_id}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/accounts/test_middleware.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'novamoc.domain.accounts._middleware'`.

- [ ] **Step 3: Implement the middleware**

Create `src/py/novamoc/domain/accounts/_middleware.py`:

```python
"""ASGIMiddleware that resolves the per-request ``TenantContext``.

Litestar 2.15+ recommends ``ASGIMiddleware`` as the subclassing API
(see https://docs.litestar.dev/latest/usage/middleware/creating-middleware.html
#creating-middleware). The class is stateless across requests; the
hardcoded credential lives in :mod:`._resolver`, not here.

The OpenAPI docs path is exempted via ``exclude_path_pattern`` so a
developer can browse ``/openapi`` without supplying a token. When a real
tenant registry lands, this regex is the natural place to add other
unauthenticated routes (health, login).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.middleware import ASGIMiddleware

from novamoc.domain.accounts._resolver import resolve_tenant

if TYPE_CHECKING:
    from litestar.types import ASGIApp, Receive, Scope, Send


class TenantMiddleware(ASGIMiddleware):
    """Stamp ``scope["state"]["tenant"]`` from the request envelope."""

    exclude_path_pattern = "^/openapi"

    async def handle(
        self,
        scope: "Scope",
        receive: "Receive",
        send: "Send",
        next_app: "ASGIApp",
    ) -> None:
        scope.setdefault("state", {})["tenant"] = resolve_tenant(scope)
        await next_app(scope, receive, send)
```

Update `src/py/novamoc/domain/accounts/__init__.py`:

```python
from novamoc.domain.accounts._context import TenantContext
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._middleware import TenantMiddleware
from novamoc.domain.accounts._resolver import resolve_tenant

__all__ = ("TenantContext", "TenantMiddleware", "TenantResolutionError", "resolve_tenant")
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/accounts/test_middleware.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/accounts/_middleware.py src/py/novamoc/domain/accounts/__init__.py tests/accounts/test_middleware.py
git commit -m "feat(accounts): TenantMiddleware stamps request.state.tenant; bypasses /openapi"
```

---

## Task 6: `provide_tenant` DI provider

**Files:**
- Create: `src/py/novamoc/domain/accounts/_di.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Create: `tests/accounts/test_di.py`

Trivial in v1, but the seam is what later tasks bind their handler signatures against.

- [ ] **Step 1: Write the failing test**

Create `tests/accounts/test_di.py`:

```python
from __future__ import annotations

from litestar import Litestar, get
from litestar.di import Provide
from litestar.testing import AsyncTestClient

from novamoc.domain.accounts import (
    TenantContext,
    TenantMiddleware,
    provide_tenant,
)
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN

_VALID_AUTH = {"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}


@get("/echo", dependencies={"tenant": Provide(provide_tenant)})
async def _echo(tenant: TenantContext) -> dict:
    return {"tenant_id": tenant.tenant_id}


def _app() -> Litestar:
    return Litestar(route_handlers=[_echo], middleware=[TenantMiddleware()])


async def test_provide_tenant_injects_context_into_handler() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/echo", headers=_VALID_AUTH)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"tenant_id": "t1"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/accounts/test_di.py -v
```

Expected: FAIL with `ImportError: cannot import name 'provide_tenant'`.

- [ ] **Step 3: Implement the provider**

Create `src/py/novamoc/domain/accounts/_di.py`:

```python
"""DI provider that hands the per-request ``TenantContext`` to handlers.

Trivially reads ``request.state.tenant``, where :class:`TenantMiddleware`
has already stamped a :class:`TenantContext`. Decoupling handlers from
``request.state`` directly lets future evolutions of the context type
(or the storage location) ride through without touching every handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.domain.accounts._context import TenantContext

if TYPE_CHECKING:
    from litestar import Request


async def provide_tenant(request: "Request") -> TenantContext:
    return request.state.tenant
```

Update `src/py/novamoc/domain/accounts/__init__.py`:

```python
from novamoc.domain.accounts._context import TenantContext
from novamoc.domain.accounts._di import provide_tenant
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._middleware import TenantMiddleware
from novamoc.domain.accounts._resolver import resolve_tenant

__all__ = (
    "TenantContext",
    "TenantMiddleware",
    "TenantResolutionError",
    "provide_tenant",
    "resolve_tenant",
)
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/accounts/test_di.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/accounts/_di.py src/py/novamoc/domain/accounts/__init__.py tests/accounts/test_di.py
git commit -m "feat(accounts): provide_tenant DI provider returns TenantContext from request.state"
```

---

## Task 7: Wire middleware + mapper into `asgi.create_app` and the test app

**Files:**
- Modify: `src/py/novamoc/asgi.py`
- Modify: `tests/conftest.py`
- Modify: `tests/schema/test_endpoint_e2e.py` (add the 401 case)

This is the integration point: the production app and the test app both register the middleware and the new mapper. The test client defaults to attaching the dev bearer header so the existing schema tests keep passing.

After this task the existing schema endpoint still uses body-side `tenant_id` — Tasks 8 and 9 retire that. But the 401 path is wireable now because middleware fires before route resolution: an unauthenticated `POST /schema` returns 401 before ever touching the schema handler.

- [ ] **Step 1: Write the failing test**

Append to `tests/schema/test_endpoint_e2e.py`:

```python
async def test_post_schema_without_authorization_returns_401(client) -> None:
    """Middleware rejects requests with no credential before the route runs."""
    # The default `client` fixture attaches Authorization; we explicitly clear it.
    resp = await client.post(
        "/schema",
        headers={"Authorization": ""},
        json={
            "type": "create_asset_type",
            "tenant_id": "tenant-e2e",  # still in payload at this point
            "entity_id": "00000000-0000-0000-0000-000000000999",
            "payload": {"name": "irrelevant"},
        },
    )
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "urn:novamoc:problems:tenant_not_resolved"
    assert body["title"] == "Tenant not resolved"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/schema/test_endpoint_e2e.py::test_post_schema_without_authorization_returns_401 -v
```

Expected: FAIL — without middleware registered, the request reaches the schema handler with whatever default behaviour and certainly does not return 401.

- [ ] **Step 3: Wire the production app**

Edit `src/py/novamoc/asgi.py`. Add imports:

```python
from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
    tenant_resolution_error_to_problem_details,
)
from novamoc.domain.accounts import TenantMiddleware, TenantResolutionError
```

Update the problem-details map:

```python
problem_details_config = ProblemDetailsConfig(
    enable_for_all_http_exceptions=True,
    exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
        SchemaError: schema_error_to_problem_details,
        TenantResolutionError: tenant_resolution_error_to_problem_details,
        msgspec.ValidationError: msgspec_validation_error_to_problem_details,
        ValidationException: litestar_validation_error_to_problem_details,
    },
)
```

Add the middleware to the `Litestar(...)` call:

```python
return Litestar(
    route_handlers=[SchemaController],
    middleware=[TenantMiddleware()],
    plugins=[...],
    openapi_config=...,
)
```

- [ ] **Step 4: Wire the test app fixture**

Edit `tests/conftest.py`. Apply the same import additions as `asgi.py`:

```python
from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
    tenant_resolution_error_to_problem_details,
)
from novamoc.domain.accounts import TenantMiddleware, TenantResolutionError
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN
```

Update the `app` fixture to register the middleware and the new mapper:

```python
exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
    SchemaError: schema_error_to_problem_details,
    TenantResolutionError: tenant_resolution_error_to_problem_details,
    msgspec.ValidationError: msgspec_validation_error_to_problem_details,
    ValidationException: litestar_validation_error_to_problem_details,
},
```

```python
return Litestar(
    route_handlers=[SchemaController],
    middleware=[TenantMiddleware()],
    plugins=[...],
    openapi_config=...,
)
```

Update the `client` fixture to attach the dev bearer token by default:

```python
@pytest.fixture
async def client(app: Litestar):
    headers = {"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}
    async with AsyncTestClient(app, headers=headers) as c:
        yield c
```

Add a session-wide `tenant_context` fixture (used by handler-level tests in Task 8):

```python
@pytest.fixture
def tenant_context() -> TenantContext:
    return TenantContext(tenant_id="t1")
```

(Imports for `TenantContext` come from `novamoc.domain.accounts`.)

- [ ] **Step 5: Run the new test + the full suite**

```bash
uv run pytest tests/schema/test_endpoint_e2e.py::test_post_schema_without_authorization_returns_401 -v
uv run pytest
```

Expected: the new 401 test passes; the existing schema e2e tests continue to pass because the `client` fixture attaches the bearer.

- [ ] **Step 6: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/asgi.py tests/conftest.py tests/schema/test_endpoint_e2e.py
git commit -m "feat(api): register TenantMiddleware and 401 mapper; default test client to dev bearer"
```

---

## Task 8: Plumb `TenantContext` through the dispatch contract

**Files (12 — exceeds the per-task heuristic):**
- Modify: `src/py/novamoc/domain/schema/_bundle.py`
- Modify: `src/py/novamoc/domain/schema/_dispatch.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type_field.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Modify: `tests/schema/test_handlers_asset_type.py`
- Modify: `tests/schema/test_handlers_asset_type_field.py`
- Modify: `tests/schema/test_handlers_maintenance_record_type.py`
- Modify: `tests/schema/test_handlers_maintenance_record_type_field.py`

**Rationale for the file count:** the dispatch contract is one conceptual seam — `Handler` alias + `dispatch` signature + 22 handler signatures + the controller call site, plus the four handler-test files that pass arguments to those handlers. Splitting source from tests would land an intermediate state where tests fail on signature mismatch with no behaviour change to anchor; splitting handler-by-handler would cycle through 4 partial dispatch tables. The single-task plumbing keeps the working tree green at the boundary.

In this task, handlers still read `req.tenant_id` for the actual value — the payload struct is unchanged. Task 9 drops `tenant_id` from the payload and flips handlers to read `tenant.tenant_id`. This split keeps each task's diff focused on one shape change.

- [ ] **Step 1: Update the `Handler` type alias**

In `src/py/novamoc/domain/schema/_bundle.py`, change the alias:

```python
Handler = Callable[[ServiceBundle, TenantContext, Any], Awaitable[SchemaCommitOutcome]]
```

Add the import:

```python
from novamoc.domain.accounts import TenantContext
```

- [ ] **Step 2: Update `dispatch`**

In `src/py/novamoc/domain/schema/_dispatch.py`:

```python
from novamoc.domain.accounts import TenantContext

async def dispatch(
    services: ServiceBundle, tenant: TenantContext, request: Any
) -> SchemaCommitOutcome:
    return await _HANDLERS[type(request)](services, tenant, request)
```

- [ ] **Step 3: Update each handler module**

For each of the four handler files, mechanical changes:

1. Add the import: `from novamoc.domain.accounts import TenantContext`.
2. Each module-level `async def <verb>(services: ServiceBundle, req: ...)` gains `tenant: TenantContext` as the second positional argument. Body is unchanged — handlers still read `req.tenant_id`.

Example diff for `_handlers/asset_type.py::create`:

```python
# before
async def create(
    services: ServiceBundle, req: _payloads.CreateAssetType
) -> SchemaCommitOutcome:
    ...

# after
async def create(
    services: ServiceBundle, tenant: TenantContext, req: _payloads.CreateAssetType
) -> SchemaCommitOutcome:
    ...  # body unchanged; still uses req.tenant_id
```

Apply this widening to all 22 verbs across the four handler modules. The function bodies do not change in this task.

- [ ] **Step 4: Update the controller**

In `src/py/novamoc/domain/schema/controllers/_schema.py`:

Add imports:

```python
from litestar.di import Provide
from novamoc.domain.accounts import TenantContext, provide_tenant
```

Register the DI provider in `SchemaController.dependencies` by appending `| {"tenant": Provide(provide_tenant)}` to the existing union expression.

Update `apply_command`'s signature and dispatch call:

```python
async def apply_command(
    self,
    data: _payloads.SchemaRequest,
    tenant: TenantContext,
    asset_type_service: ...,
    ...
) -> _payloads.SchemaResponse:
    services = ServiceBundle(...)
    outcome = await dispatch(services, tenant, data)
    ...
```

The read handler `read_snapshot` is **not** updated in this task — it still uses `tenant_id: str` from the URL path. Task 10 migrates it.

- [ ] **Step 5: Update the four handler test files**

Each handler test file calls handlers like `await create(services, req)`. Update each call to `await create(services, tenant_context, req)`, where `tenant_context` is the fixture added to `conftest.py` in Task 7. Handler tests must also accept the fixture parameter:

```python
# before
async def test_create_asset_type_inserts_row(services, ...) -> None:
    ...
    await asset_type.create(services, req)

# after
async def test_create_asset_type_inserts_row(services, tenant_context, ...) -> None:
    ...
    await asset_type.create(services, tenant_context, req)
```

Sweep all four files. The fixture is already wired (Task 7); no new conftest changes needed.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest
```

Expected: all tests pass. Handlers still read `req.tenant_id`; payload still carries it; behaviour unchanged.

- [ ] **Step 7: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/py/novamoc/domain/schema/_bundle.py \
        src/py/novamoc/domain/schema/_dispatch.py \
        src/py/novamoc/domain/schema/_handlers/ \
        src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/schema/test_handlers_*.py
git commit -m "refactor(schema): plumb TenantContext through dispatch into handlers"
```

---

## Task 9: Drop `tenant_id` from `_SchemaCommand`; flip handlers to `tenant.tenant_id`; add `forbid_unknown_fields`

**Files:**
- Modify: `src/py/novamoc/domain/schema/_payloads.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/asset_type_field.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type.py`
- Modify: `src/py/novamoc/domain/schema/_handlers/maintenance_record_type_field.py`
- Modify: `tests/schema/test_payloads.py`
- Modify: `tests/schema/test_endpoint_e2e.py`

This is the second seam: the wire payload and the handler internals. Together they swing from "tenant_id from body" to "tenant_id from `tenant.tenant_id` (DI-injected from middleware)".

- [ ] **Step 1: Update the failing test surface**

In `tests/schema/test_endpoint_e2e.py`, drop `"tenant_id": _T` from every JSON body. Delete the `_T` constant if no longer referenced (it isn't, after this sweep).

In `tests/schema/test_payloads.py`, every assertion that reads or constructs a struct with `tenant_id` updates accordingly. Where the test verified `forbid_unknown_fields=True` rejects extra keys, ensure a case for `{"tenant_id": "t1"}` on a command struct is added (this should now be rejected as `invalid_payload_shape`).

Add a new assertion in `test_payloads.py`:

```python
def test_command_struct_rejects_legacy_tenant_id_field() -> None:
    import msgspec
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(
            b'{"type":"create_asset_type","tenant_id":"t1","entity_id":"00000000-0000-0000-0000-000000000001","payload":{"name":"X"}}',
            type=_payloads.SchemaRequest,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/schema/test_endpoint_e2e.py tests/schema/test_payloads.py -v
```

Expected: payload tests fail (`tenant_id` still present in struct); e2e tests pass (payload struct silently accepts the now-legacy field absent `forbid_unknown_fields`).

- [ ] **Step 3: Update `_payloads.py`**

In `src/py/novamoc/domain/schema/_payloads.py`:

1. Add `forbid_unknown_fields=True` to `_SchemaCommand`:

```python
class _SchemaCommand(msgspec.Struct, tag=_snake_tag, forbid_unknown_fields=True):
    ...
```

2. Remove `tenant_id: str` from each of the 22 command struct subclasses.

- [ ] **Step 4: Flip each handler from `req.tenant_id` to `tenant.tenant_id`**

For each handler in the four `_handlers/*.py` files: replace every `req.tenant_id` reference with `tenant.tenant_id`. The signature already takes `tenant: TenantContext` from Task 8; this step flips the value source.

Sample diff for `_handlers/asset_type.py::create`:

```python
# before
await services.asset_type.create(
    data={
        "tenant_id": req.tenant_id,
        ...
    },
    auto_commit=False,
)

# after
await services.asset_type.create(
    data={
        "tenant_id": tenant.tenant_id,
        ...
    },
    auto_commit=False,
)
```

Apply this swap to every `req.tenant_id` reference in the four handler files. (Use `rg req.tenant_id` to enumerate them — should be roughly two references per handler.)

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest
```

Expected: all tests pass. Wire requests no longer carry `tenant_id`; handlers no longer read it from `req`; the payload struct rejects the legacy field outright.

- [ ] **Step 6: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/domain/schema/_payloads.py \
        src/py/novamoc/domain/schema/_handlers/ \
        tests/schema/test_payloads.py \
        tests/schema/test_endpoint_e2e.py
git commit -m "refactor(schema): drop tenant_id from POST /schema body; handlers read tenant.tenant_id"
```

---

## Task 10: Migrate read endpoint to `GET /schema`; delete `tenant_not_found` machinery

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `src/py/novamoc/domain/schema/_errors.py`
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `src/py/novamoc/domain/schema/controllers/_schema.py`
- Modify: `tests/schema/test_read_endpoint_e2e.py`
- Modify: `tests/api/test_problem_details.py`

The read endpoint loses its URL parameter; the `KNOWN_TENANT_IDS` registry, the `TenantNotFoundError`, and the `TENANT_NOT_FOUND` error code all retire together.

- [ ] **Step 1: Rewrite read-endpoint e2e tests**

In `tests/schema/test_read_endpoint_e2e.py`:

1. Switch every `f"/schema/{_T}"` URL to `"/schema"`.
2. Delete `_T = "t1"` (no longer needed).
3. Delete `test_get_schema_unknown_tenant_returns_404_problem_details` and `test_if_none_match_unknown_tenant_still_returns_404` — those failure modes do not exist any more.
4. Add a new test asserting `GET /schema` without `Authorization` returns 401 `tenant_not_resolved`:

```python
async def test_get_schema_without_authorization_returns_401(client) -> None:
    resp = await client.get("/schema", headers={"Authorization": ""})
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "urn:novamoc:problems:tenant_not_resolved"
```

- [ ] **Step 2: Delete the legacy mapper test case**

In `tests/api/test_problem_details.py`, delete `test_schema_error_tenant_not_found_renders_404_with_extras`. Remove its imports if no longer referenced.

- [ ] **Step 3: Run the tests to verify the deletion-related failures**

```bash
uv run pytest tests/schema/test_read_endpoint_e2e.py tests/api/test_problem_details.py -v
```

Expected: the new 401 read test fails (controller still mounts `GET /schema/{tenant_id}`); the deletion of the old tests is mechanical.

- [ ] **Step 4: Migrate the controller**

In `src/py/novamoc/domain/schema/controllers/_schema.py`:

1. Update the `get` decorator on `read_snapshot` from `@get("/{tenant_id:str}")` to `@get("/")`.
2. Change the signature: drop `tenant_id: str` from the parameter list; add `tenant: TenantContext`.
3. Read `tenant.tenant_id` where the function previously used `tenant_id` (the parameter from the path).
4. Delete the `if tenant_id not in KNOWN_TENANT_IDS` block and the `TenantNotFoundError` raise that follows it.
5. Remove the `from novamoc.config import KNOWN_TENANT_IDS` and `TenantNotFoundError` imports (use `rg` to confirm the symbols are no longer referenced anywhere in `_schema.py`).
6. Add `from novamoc.domain.accounts import TenantContext` if not already present (Task 8 added it via the `apply_command` path; this is a sanity check).

- [ ] **Step 5: Delete `KNOWN_TENANT_IDS`**

Replace the body of `src/py/novamoc/config.py` with just the docstring (or delete the file if it ends up empty enough that the docstring is meaningless). For safety, keep the module file with the docstring for now:

```python
"""Application-level configuration constants.

Today this module is empty — pre-auth dev configuration that previously
lived here (the ``KNOWN_TENANT_IDS`` stub) was retired by ADR-017.
Re-introduce constants here when they need cross-module sharing.
"""

from __future__ import annotations
```

- [ ] **Step 6: Delete `TENANT_NOT_FOUND` from the schema error machinery**

In `src/py/novamoc/domain/schema/_errors.py`:

1. Delete `ErrorCode.TENANT_NOT_FOUND` from the enum.
2. Delete its `_DEFAULT_MESSAGES` row.
3. Delete the `TenantNotFoundError` subclass.

In `src/py/novamoc/api/_problem_details.py`:

1. Delete the `ErrorCode.TENANT_NOT_FOUND` rows from `_TITLES` and `_STATUS_CODES`.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest
```

Expected: all tests pass. The old 404 path is gone; the new 401 path replaces it; the read endpoint reads its tenant from DI.

- [ ] **Step 8: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/py/novamoc/config.py \
        src/py/novamoc/domain/schema/_errors.py \
        src/py/novamoc/api/_problem_details.py \
        src/py/novamoc/domain/schema/controllers/_schema.py \
        tests/schema/test_read_endpoint_e2e.py \
        tests/api/test_problem_details.py
git commit -m "refactor(schema): GET /schema reads tenant from DI; retire tenant_not_found"
```

---

## Task 11: README + final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Development credentials" subsection to `README.md`**

Append a section:

```markdown
## Development credentials

Every API request requires a bearer token in the `Authorization` header.
The dev environment hardcodes a single token that maps to tenant `t1`.

Find the token value in `src/py/novamoc/domain/accounts/_resolver.py`
(constant `_TENANT_T1_DEV_TOKEN`). Send it as:

```
Authorization: Bearer <token>
```

Example with `curl`:

```sh
curl -H "Authorization: Bearer t1-dev-token" \
     http://localhost:8000/schema
```

The OpenAPI doc at `/openapi` is exempt from the credential check, so it
is browsable without a token.
```

- [ ] **Step 2: Final verification matrix**

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
```

Expected: all green; total test count grew by the unit tests added under `tests/accounts/` (≈14 tests across `test_context.py`, `test_resolver.py`, `test_middleware.py`, `test_di.py`) and the wire-level 401 cases (≈2).

- [ ] **Step 3: Confirm the dev server still starts**

```bash
uv run litestar --app novamoc.asgi:create_app routes
```

Expected: prints `POST /schema` and `GET /schema` (no `{tenant_id}` path parameter).

- [ ] **Step 4: Sanity-check the OpenAPI doc**

```bash
uv run python -c "import json; from novamoc.asgi import create_app; print(json.dumps(create_app().openapi_schema.to_schema(), indent=2))" | head -40
```

Expected: 401 response is documented on both `POST /schema` and `GET /schema`; no `tenant_id` path parameter on the GET; no `tenant_not_found` failure mode anywhere.

- [ ] **Step 5: Commit and push**

```bash
git add README.md
git commit -m "docs(readme): document the dev bearer token and OpenAPI bypass"
git push
```

---

## Self-Review

**Spec coverage check:**

- *ADR-017 + ADR-014 status flip* — Task 1.
- *`TenantContext` frozen struct* — Task 2.
- *`TenantResolutionError` + 401 mapper registered in both apps* — Tasks 3 and 7.
- *Resolver reads Bearer token, matches constant, raises on miss* — Task 4 (unit) + Task 7 (registered in production app).
- *`ASGIMiddleware` with `exclude_path_pattern = "^/openapi"`* — Task 5.
- *DI provider returning `TenantContext`* — Task 6.
- *Test client defaults to attaching the dev bearer header; 401 e2e cases on both endpoints* — Tasks 7 and 10.
- *Drop `tenant_id` from POST /schema body; `forbid_unknown_fields=True` on `_SchemaCommand`* — Task 9.
- *Handlers gain `tenant: TenantContext`; dispatch contract widens* — Task 8.
- *Read endpoint moves to `GET /schema`; `KNOWN_TENANT_IDS` and `TenantNotFoundError` retire* — Task 10.
- *README documents the dev token* — Task 11.

No spec requirement is uncovered.

**Placeholder scan:** no "TBD", no "implement later", no "add appropriate error handling". Each step contains the actual code or command needed.

**Type consistency:** `resolve_tenant(scope) -> TenantContext` consistent across Tasks 4, 5, 7. `TenantMiddleware().handle(scope, receive, send, next_app)` matches Litestar 2.21.1's signature (verified). `provide_tenant(request) -> TenantContext` consistent across Tasks 6 and 8. Handler signature `async def <verb>(services: ServiceBundle, tenant: TenantContext, req: ...)` consistent across Tasks 8 and 9.

**File-count exceptions:** Task 8 (12 files) is flagged inline. The conceptual seam (dispatch contract) does not split cleanly without artificial intermediate states; the plan accepts the heuristic violation with rationale.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-04-tenant-resolution-middleware.md`. Ready for execution.
