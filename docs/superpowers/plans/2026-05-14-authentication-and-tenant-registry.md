# Authentication & Tenant Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the design at `docs/superpowers/specs/2026-05-14-authentication-and-tenant-registry-design.md` — the v2 credential machinery ADR-017 deferred. Real `tenants` / `users` / `user_tenant_memberships` / `sessions` tables with UUIDv7 tenant identity, argon2id password hashing, server-side session cookies via advanced-alchemy, `POST /auth/login` + `POST /auth/logout` + `GET /auth/me`, and a CLI as the single bootstrap path (dev via `just bootstrap-dev`; production via the same commands in an init container). The N:1 invariant (one tenant per user) is enforced at the `UserTenantMembershipService.create` write path with a 409 `user_already_has_tenant`. Closes issue #19.

**Architecture:** The resolver-as-swap-point structure from ADR-017 is preserved. `domain/accounts/_resolver.py` is rewritten from "header → constant match → tenant string" into "session → user + active tenant lookup → `(Principal, RequestAuth)`". `AuthenticationMiddleware.authenticate_request` becomes async-with-DB-access; `TenantContextMiddleware` and the three storage-layer listeners are untouched. Every existing `tenant_id: Mapped[str]` column migrates to `Mapped[uuid.UUID]` (TenantScopedMixin, projection tables, event_log, schema_change_log, RequestAuth, the ContextVar, scenarios) in one commit so the boundary stays green. The new auth-layer tables live under `db/models/_auth/` and are NOT tenant-scoped — they short-circuit the listener's column-presence heuristic naturally. `SQLAlchemyAsyncSessionBackend` from advanced-alchemy stores sessions in the same DB. No environment-conditional code in the server: there is no seed function, no startup hook, no `dev_seed_default_admin` setting.

**Revision history:** This is revision 2 of the plan. Changes from revision 1, surfaced for reviewer convenience:
- Tenant ID is `uuid.UUID` (was a slug `str`). Cascading `tenant_id` column-type migration folded into Task 2.
- `_seed.py` / `seed_default_admin` / `dev_seed_default_admin` / `NOVAMOC_DEV_SEED_DEFAULT_ADMIN` all dropped. Task 9 removed. Bootstrap is via CLI (`just bootstrap-dev` recipe).
- N:1 invariant enforced at `UserTenantMembershipService.create`, not at login. `MultipleMembershipsUnsupportedError` renamed to `UserAlreadyHasTenantError`; the 409 surface moves from `POST /auth/login` to the membership-write path (CLI).
- `Principal.user_id` renamed to `Principal.id`.

**Tech Stack:** Python 3.14, Litestar 2.21.1, msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, argon2-cffi, Click (CLI), Svelte 5 + Vite (login page), pytest (asyncio auto mode), uv, ruff, ty.

**Milestone:** Proposed as **M5: Authentication & tenant registry** (numbering follows the M1–M4 convention in existing issues). Blocks M2 (`GET /events?since` for catch-up) and M3 (WS-transport with per-tenant subscriber registry) in the sense that both presume a real tenant identity. Does **not** block any in-flight M1 work.

---

## File map

**Created:**
- `docs/adr/020-authentication-and-tenant-registry.md` — the milestone ADR.
- `src/py/novamoc/db/models/_auth/__init__.py`
- `src/py/novamoc/db/models/_auth/_tenant.py` — `Tenant` model (UUIDv7 PK from `UUIDAuditBase`).
- `src/py/novamoc/db/models/_auth/_user.py` — `User` model.
- `src/py/novamoc/db/models/_auth/_membership.py` — `UserTenantMembership` model.
- `src/py/novamoc/db/models/_auth/_session.py` — `Session` model via advanced-alchemy's mixin.
- `src/py/novamoc/domain/accounts/_principal.py` — `Principal` frozen `msgspec.Struct` with `id` + `username`.
- `src/py/novamoc/domain/accounts/_password.py` — `PasswordHasher` accessor.
- `src/py/novamoc/domain/accounts/_services.py` — `TenantService`, `UserService`, `UserTenantMembershipService` (the last enforces the N:1 invariant on `create`).
- `src/py/novamoc/domain/accounts/_payloads.py` — `LoginRequest`, `MeResponse`, `MePrincipal`, `MeTenant`.
- `src/py/novamoc/domain/accounts/_handlers.py` — `login`, `logout`, `me` handler functions.
- `src/py/novamoc/domain/accounts/controllers/__init__.py`, `controllers/_auth.py` — `AuthController`.
- `src/py/novamoc/cli.py` — Click CLI entry point + sub-commands.
- `src/js/web/src/routes/login/+page.svelte` — the SPA login page.
- `tests/_constants.py` — `DEV_TENANT_ID` UUID constant used by scenarios + fixtures (replaces every `"t1"` literal).
- `tests/accounts/test_password.py`, `test_membership_service.py`, `test_resolver_session.py`, `test_login_e2e.py`, `test_logout_e2e.py`, `test_me_e2e.py`, `test_cli.py`.

**Modified:**
- `src/py/novamoc/db/models/_mixins.py` — `TenantScopedMixin.tenant_id` flips from `Mapped[str]` to `Mapped[uuid.UUID]`.
- Every projection table under `src/py/novamoc/db/models/data/` and schema table under `src/py/novamoc/db/models/schema/` — picks up the type change transitively via the mixin (no per-file edit needed unless a model declares `tenant_id` directly).
- `src/py/novamoc/db/models/data/_event.py` (event_log) and `src/py/novamoc/db/models/schema/_change_log.py` — the hand-declared `tenant_id` columns flip to `uuid.UUID` too.
- `src/py/novamoc/db/_tenant_context.py` — `current_tenant_id: ContextVar[uuid.UUID | None]`; `use_tenant(tenant_id: uuid.UUID)`.
- `src/py/novamoc/domain/accounts/_auth.py` — `RequestAuth.tenant_id: uuid.UUID`.
- `src/py/novamoc/asgi.py` — session middleware, `AuthController`, new problem-details mappers, hasher on `app.state`. **No seed hook.**
- `src/py/novamoc/config.py` — `AuthSettings` field on `Settings` (no `dev_seed_default_admin`).
- `src/py/novamoc/api/_problem_details.py` — add `LOGIN_FAILED` and `USER_ALREADY_HAS_TENANT`.
- `src/py/novamoc/domain/_errors.py` — register the two new error codes on `ErrorCode`.
- `src/py/novamoc/domain/accounts/_resolver.py` — full rewrite.
- `src/py/novamoc/domain/accounts/_middleware.py` — async authenticate_request that reads session + DB.
- `src/py/novamoc/domain/accounts/_errors.py` — `LoginFailedError`, `UserAlreadyHasTenantError`.
- `src/py/novamoc/domain/accounts/__init__.py` — re-exports.
- `src/py/novamoc/db/_listeners.py` — small allow-list pin (defensive).
- `src/py/novamoc/db/models/__init__.py` — import the new `_auth` sub-package so its tables register on the shared metadata.
- `tests/conftest.py` — drop the bearer header; add `dev_admin`, `authenticated_client`, `unauth_client`; switch the autouse `tenant` fixture default to `DEV_TENANT_ID`.
- `tests/data/scenarios.py` and any `tests/data/*.json` carrying `"t1"` — replace with `DEV_TENANT_ID`.
- `pyproject.toml` — add `argon2-cffi` and `click` dependencies; declare the `novamoc` CLI entry point under `[project.scripts]`.
- `justfile` — add `bootstrap-dev` recipe.
- `README.md` — document the new login flow and the bootstrap recipe.

**Deleted:**
- `_TENANT_T1_DEV_TOKEN` constant and the bearer-matching code in `_resolver.py`.
- Bearer-header default in `tests/conftest.py::client`.
- The string `"t1"` everywhere it appeared as a tenant identifier (replaced by `DEV_TENANT_ID`).

---

## Conventions

- **TDD throughout.** Every behavioural task starts with a failing test. Watch the test fail before implementing.
- **No DB mocks.** All DB-touching tests use the real in-memory aiosqlite per `tests/conftest.py`.
- **`uv run` everything.** Tests, lint, type-check all go through `uv run`.
- **Async via auto mode.** Tests do not need `@pytest.mark.asyncio`.
- **One commit per task.** Working tree green at every commit boundary. Hooks honoured (no `--no-verify`).
- **ADR-first.** Task 1 lands ADR-020 before any code lands.
- **Layering rule.** `src/py/novamoc/db/` must not import `advanced_alchemy.extensions.litestar`. New auth models live under `db/models/_auth/` and use `advanced_alchemy.base` only. The session backend's web-facing config lives in `asgi.py`; the model mixin (a `DefaultBase`-compatible thing) imports from the storage half.
- **Ratchet discipline.** Run `just ratchet` after each task; counts should not increase. New ignores require justification per CLAUDE.md.
- **`pre-release: breaking changes are fine`.** The bearer-token wire format goes away in lockstep with the new session cookie; no compatibility shim.
- **File-count heuristic.** Cap at 8 files per task; tasks that legitimately exceed it (the conftest migration in Task 12, the resolver rewrite in Task 11) flag the rationale inline.

---

## Task 1: Land ADR-020 and milestone scaffolding

**Files:**
- Create: `docs/adr/020-authentication-and-tenant-registry.md`

The ADR is the decision record this milestone sits on top of. Land it first so reviewers reading commit history see the decision recorded before its implementation.

- [ ] **Step 1: Write ADR-020**

Use `docs/adr/_template.md` as the starting point (post-template MADR shape). Required content per the spec's "ADR coordination" section:

- **Frontmatter:** `status: accepted`, `date: 2026-05-14`, `category: authentication`, decision-makers list per repo convention.
- **Context:** ADR-017 deferred the credential format ("v1 hardcodes a single token in source. No rotation, expiry, or revocation. Acceptable for the dev period only"). The bearer constant must now be replaced with a real registry; the principal slot (`RequestAuth.user`) must be populated; issue #19 must close.
- **Decision drivers:** preserve ADR-017's dispatch contract; reuse the existing 401 wire shape; pick a session story that does not introduce a new datastore; expose a real rejection path for production deployment hygiene.
- **Considered options:** stateless JWT in `Authorization`; JWT in cookie; session cookie with server-side store. List the chosen option first.
- **Decision outcome:** session cookie via advanced-alchemy's `SQLAlchemyAsyncSessionBackend`. The principal/scope split inherits from ADR-017. The `tenants.id` PK is a UUIDv7 (from `UUIDAuditBase`); every existing `tenant_id: Mapped[str]` column migrates to `Mapped[uuid.UUID]` in lockstep. The membership table is N-to-N from day one with a v1 invariant of exactly-one-membership enforced at the service-layer write path (`UserTenantMembershipService.create` raises `UserAlreadyHasTenantError` → 409). No dev-only code in the server — bootstrap is via the CLI in every environment, wrapped locally by `just bootstrap-dev`.
- **Consequences:** Good — instant revocation; one DB; structurally same 401 wire shape; principal/scope split is forward-compatible. Bad — long sessions only refresh on expiry (no inactivity timeout in v1); the dev `admin`/`admin` credential is in source (same trust model as ADR-017's bearer constant); no API tokens for CLI/automation.
- **Confirmation:** unit tests in `tests/accounts/test_resolver_session.py` pin the resolver's accept/reject behaviour; e2e tests in `test_login_e2e.py` / `test_logout_e2e.py` / `test_me_e2e.py` pin the wire contract; cross-tenant isolation tests under the new auth stack confirm the existing tenant-scoping listener machinery still does the right thing.
- **More information:** cite ADR-017 (defers this work; its dispatch contract holds), ADR-014 (superseded by 017), ADR-008 (where future authorization Guards plug in), ADR-016 (problem-details rendering this depends on). Link to issue #19 (closed by this milestone) and to the spec at `docs/superpowers/specs/2026-05-14-authentication-and-tenant-registry-design.md`.

ADR-020 does **not** supersede ADR-017 — ADR-017's structural decisions hold; ADR-020 fills in their v2 details.

- [ ] **Step 2: Run the test suite to confirm nothing regressed**

```bash
uv run pytest
```

Expected: same baseline as pre-task.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/020-authentication-and-tenant-registry.md
git commit -m "docs(adr): ADR-020 authentication and tenant registry"
```

---

## Task 2: Migrate `tenant_id` columns to `uuid.UUID`; add `Tenant` model + service

**Files (12 — exceeds the per-task heuristic):**
- Modify: `pyproject.toml` — add `argon2-cffi` and `click` dependencies.
- Modify: `src/py/novamoc/db/models/_mixins.py` — `TenantScopedMixin.tenant_id: Mapped[uuid.UUID]`.
- Modify: `src/py/novamoc/db/models/data/_event.py` — hand-declared `tenant_id` flips to `uuid.UUID`.
- Modify: `src/py/novamoc/db/models/schema/_change_log.py` — same.
- Modify: `src/py/novamoc/db/_tenant_context.py` — `ContextVar[uuid.UUID | None]`, `use_tenant(tenant_id: uuid.UUID)`.
- Modify: `src/py/novamoc/domain/accounts/_auth.py` — `RequestAuth.tenant_id: uuid.UUID`.
- Modify: `src/py/novamoc/domain/accounts/_resolver.py` — current bearer-matcher returns `uuid.UUID` (the constant changes from `"t1"` to a UUID literal — this is interim; Task 11 replaces this whole module).
- Create: `tests/_constants.py` — `DEV_TENANT_ID: uuid.UUID = uuid.UUID("...")`, a fixed UUIDv7 literal; `DEV_TENANT_ID_A` / `DEV_TENANT_ID_B` for cross-tenant tests.
- Modify: `tests/conftest.py` — autouse `tenant` fixture default flips from `"t1"` to `DEV_TENANT_ID`.
- Modify: `tests/data/scenarios.py` (and any JSON under `tests/data/`) — replace `"t1"` with `DEV_TENANT_ID`.
- Create: `src/py/novamoc/db/models/_auth/__init__.py`, `_tenant.py`.
- Modify: `src/py/novamoc/db/models/__init__.py` — import the `_auth` sub-package.
- Create: `src/py/novamoc/domain/accounts/_services.py` — `TenantService` (no slug validator; the inherited UUIDv7 PK is the constraint).
- Create: `tests/accounts/test_tenant_model.py`.

**Rationale for the file count:** the tenant-identity type migration is one conceptual seam — column type, ContextVar type, `RequestAuth` shape, and every test scenario flip together. Splitting them leaves intermediate states where the columns disagree with the ContextVar (or `RequestAuth`) and the existing schema-endpoint tests fail because a `uuid.UUID` `tenant_id` won't match a string-typed predicate. The single-task migration keeps the boundary green. Adding the `Tenant` model in the same commit folds in cleanly because it's the table the new types FK to.

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml`. Append to `[project.dependencies]`:

```toml
"argon2-cffi>=23.1.0",
"click>=8.1.7",
```

Run `uv sync` to update the lock file.

- [ ] **Step 2: Write the failing tests**

Create `tests/_constants.py`:

```python
"""Shared test constants. Imported by scenarios + fixtures + tests."""

from __future__ import annotations

import uuid

# A fixed UUIDv7 — picked once and inlined here so scenarios and fixtures
# all reference the same value. Don't reuse uuid.uuid4() at import time:
# tests would lose determinism.
DEV_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-000000000001")
DEV_TENANT_ID_A = uuid.UUID("01900000-0000-7000-8000-00000000000a")
DEV_TENANT_ID_B = uuid.UUID("01900000-0000-7000-8000-00000000000b")
```

Create `tests/accounts/test_tenant_model.py`:

```python
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.no_tenant


async def test_tenant_row_inserts_and_reads(session) -> None:
    from novamoc.db.models._auth import Tenant

    tenant = Tenant(display_name="Development")
    session.add(tenant)
    await session.flush()

    assert isinstance(tenant.id, uuid.UUID)
    result = await session.get(Tenant, tenant.id)
    assert result is not None
    assert result.display_name == "Development"
    assert result.disabled_at is None


async def test_tenant_service_create_returns_uuid_id(session) -> None:
    from novamoc.domain.accounts._services import TenantService

    service = TenantService(session=session)
    tenant = await service.create({"display_name": "Acme"})
    assert isinstance(tenant.id, uuid.UUID)
```

Note the `no_tenant` marker — the `tenants` table is not tenant-scoped, so the autouse `tenant` fixture's auto-injection would be a false signal.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/accounts/test_tenant_model.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Flip the column types**

In `src/py/novamoc/db/models/_mixins.py`:

```python
import uuid
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column


@declarative_mixin
class TenantScopedMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, sort_order=-200)
```

In `src/py/novamoc/db/models/data/_event.py` (event_log): the hand-declared `tenant_id` column flips to `Mapped[uuid.UUID]`. Same in `src/py/novamoc/db/models/schema/_change_log.py`.

In `src/py/novamoc/db/_tenant_context.py`:

```python
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
import uuid

current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar(
    "novamoc_current_tenant_id", default=None
)


@contextmanager
def use_tenant(tenant_id: uuid.UUID) -> Iterator[None]:
    token = current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)
```

In `src/py/novamoc/domain/accounts/_auth.py`:

```python
import uuid
import msgspec


class RequestAuth(msgspec.Struct, frozen=True):
    tenant_id: uuid.UUID
```

In `src/py/novamoc/domain/accounts/_resolver.py` (the v1 module that Task 11 will rewrite — for now just update the constant + return type):

```python
import uuid

_TENANT_T1_DEV_TOKEN = "t1-dev-token"  # noqa: S105
_TENANT_T1: uuid.UUID = uuid.UUID("01900000-0000-7000-8000-000000000001")  # matches DEV_TENANT_ID

def resolve_tenant(headers) -> uuid.UUID:
    # ...existing body, returning _TENANT_T1 instead of "t1"
```

- [ ] **Step 5: Update the test data + conftest**

In `tests/conftest.py`:
- Import `DEV_TENANT_ID` from `tests._constants`.
- Change the autouse `tenant` fixture's default from `"t1"` to `DEV_TENANT_ID`.
- Update the parametrize examples in the docstring (`["t-a", "t-b"]` → `[DEV_TENANT_ID_A, DEV_TENANT_ID_B]`).

In `tests/data/scenarios.py`:
- Replace `tenant_id: "t1"` (or whatever the literal currently is) with `DEV_TENANT_ID`.
- If scenarios live as JSON, either convert to Python literals so they can reference the constant, or write a small loader pass that swaps the string for the UUID.

In `tests/schema/test_cross_tenant_isolation.py`:
- Replace `"t-a"` / `"t-b"` with `DEV_TENANT_ID_A` / `DEV_TENANT_ID_B`.

- [ ] **Step 6: Implement `Tenant` and `TenantService`**

Create `src/py/novamoc/db/models/_auth/__init__.py`:

```python
"""Auth-layer models.

Tenant registry, user accounts, user-tenant memberships, and sessions.
These tables are NOT tenant-scoped — they are auth infrastructure. The
three storage-layer listeners in ``db/_listeners.py`` skip them because
they do not carry a ``tenant_id`` column.
"""

from __future__ import annotations

from novamoc.db.models._auth._tenant import Tenant

__all__ = ("Tenant",)
```

Create `src/py/novamoc/db/models/_auth/_tenant.py`:

```python
"""Tenant registry model (ADR-020).

PK is the inherited UUIDv7 from ``UUIDAuditBase`` — no override. The
tenant identity is a UUID across the whole codebase; the registry row
is just one place that identity is anchored.
"""

from __future__ import annotations

from datetime import datetime

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(UUIDAuditBase):
    __tablename__ = "tenants"

    display_name: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)
```

Update `src/py/novamoc/db/models/__init__.py`:

```python
import novamoc.db.models._auth  # noqa: F401
```

Create `src/py/novamoc/domain/accounts/_services.py`:

```python
"""Advanced-alchemy services for the auth-layer tables.

Thin ``SQLAlchemyAsyncRepositoryService`` wrappers. Validation
(uniqueness, foreign-key existence) is enforced at the database level;
the only service-level rule lives on ``UserTenantMembershipService``
(Task 4) which enforces the v1 one-membership-per-user invariant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncRepositoryService

from novamoc.db.models._auth import Tenant

if TYPE_CHECKING:
    from collections.abc import Mapping


class TenantService(SQLAlchemyAsyncRepositoryService[Tenant]):
    class Repo(SQLAlchemyAsyncRepositoryService[Tenant].repository_type):
        model_type = Tenant

    repository_type = Repo
```

(The exact `SQLAlchemyAsyncRepositoryService` boilerplate may need adjustment to match advanced-alchemy's current API; the existing services under `domain/schema/services/` are the reference shape.)

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/accounts/test_tenant_model.py -v
uv run pytest
```

Expected: the new tenant tests pass; the full suite still passes after the type migration. If existing tests fail, they're almost certainly cases where a string `"t1"` slipped through — `rg '"t1"' tests/` to find stragglers.

- [ ] **Step 8: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
just ratchet
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock \
        src/py/novamoc/db/ \
        src/py/novamoc/domain/accounts/ \
        tests/_constants.py \
        tests/conftest.py \
        tests/data/ \
        tests/schema/test_cross_tenant_isolation.py \
        tests/accounts/test_tenant_model.py
git commit -m "feat(accounts): migrate tenant_id to uuid.UUID; add Tenant model"
```

---

## Task 3: `User` model + service + password column

**Files:**
- Create: `src/py/novamoc/db/models/_auth/_user.py`
- Modify: `src/py/novamoc/db/models/_auth/__init__.py`
- Modify: `src/py/novamoc/domain/accounts/_services.py` — add `UserService`.
- Create: `tests/accounts/test_user_model.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_user_model.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_tenant


async def test_user_row_inserts_and_reads(session) -> None:
    from novamoc.db.models._auth import User

    user = User(username="alice", password_hash="$argon2id$v=19$m=...")
    session.add(user)
    await session.flush()

    fetched = await session.get(User, user.id)
    assert fetched is not None
    assert fetched.username == "alice"
    assert fetched.disabled_at is None


async def test_username_unique_constraint(session) -> None:
    from sqlalchemy.exc import IntegrityError

    from novamoc.db.models._auth import User

    session.add(User(username="alice", password_hash="x"))
    await session.flush()
    session.add(User(username="alice", password_hash="y"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_user_service_case_folds_username(session) -> None:
    from novamoc.domain.accounts._services import UserService

    service = UserService(session=session)
    user = await service.create({"username": "Alice", "password_hash": "x"})
    assert user.username == "alice"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/accounts/test_user_model.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `User`**

Create `src/py/novamoc/db/models/_auth/_user.py`:

```python
"""User account model (ADR-020).

PK is a UUIDv7 (from ``UUIDAuditBase``) because usernames can be renamed
in principle; the stable identity is the surrogate. ``password_hash``
carries the full argon2id encoded string. ``disabled_at`` is a timestamp
(not a boolean) so future audit displays can show when a user was
disabled at no extra cost.
"""

from __future__ import annotations

from datetime import datetime

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy.orm import Mapped, mapped_column


class User(UUIDAuditBase):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)
```

Update `_auth/__init__.py`:

```python
from novamoc.db.models._auth._tenant import Tenant
from novamoc.db.models._auth._user import User

__all__ = ("Tenant", "User")
```

- [ ] **Step 4: Implement `UserService`**

Append to `src/py/novamoc/domain/accounts/_services.py`:

```python
import unicodedata

from novamoc.db.models._auth import User


def _fold_username(value: str) -> str:
    """NFKC + lowercase per the spec's anti-impersonation rule."""
    return unicodedata.normalize("NFKC", value).casefold()


class UserService(SQLAlchemyAsyncRepositoryService[User]):
    class Repo(SQLAlchemyAsyncRepositoryService[User].repository_type):
        model_type = User

    repository_type = Repo

    async def create(self, data: Mapping[str, Any] | User, **kwargs: Any) -> User:
        if isinstance(data, Mapping):
            username = data.get("username")
            if isinstance(username, str):
                data = {**data, "username": _fold_username(username)}
        return await super().create(data=data, **kwargs)

    async def get_by_username(self, username: str) -> User | None:
        return await self.get_one_or_none(username=_fold_username(username))
```

(`SQLAlchemyAsyncRepositoryService` may need a small adjustment — match the existing `domain/schema/services/` patterns for `get_one_or_none` plumbing.)

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/accounts/test_user_model.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/db/models/_auth/ \
        src/py/novamoc/domain/accounts/_services.py \
        tests/accounts/test_user_model.py
git commit -m "feat(accounts): User model + case-folded username service"
```

---

## Task 4: `UserTenantMembership` model + service with N:1 write-time invariant

**Files:**
- Create: `src/py/novamoc/db/models/_auth/_membership.py`
- Modify: `src/py/novamoc/db/models/_auth/__init__.py`
- Modify: `src/py/novamoc/domain/accounts/_services.py` — add `UserTenantMembershipService` with the N:1 invariant on `create`.
- Modify: `src/py/novamoc/domain/accounts/_errors.py` — `UserAlreadyHasTenantError` (lands here so the service can raise it).
- Create: `tests/accounts/test_membership_model.py`
- Create: `tests/accounts/test_membership_service.py`

The model is N-to-N at the schema level; the service-layer write check enforces the v1 invariant. v2's switch-tenant work relaxes the service check; the table doesn't move.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_membership_model.py`:

```python
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.no_tenant


async def test_membership_inserts_with_real_fks(session) -> None:
    from novamoc.db.models._auth import Tenant, User, UserTenantMembership

    tenant = Tenant(display_name="Development")
    user = User(username="alice", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()

    membership = UserTenantMembership(user_id=user.id, tenant_id=tenant.id)
    session.add(membership)
    await session.flush()

    fetched = await session.get(UserTenantMembership, (user.id, tenant.id))
    assert fetched is not None


async def test_membership_pk_is_unique_pair(session) -> None:
    from sqlalchemy.exc import IntegrityError

    from novamoc.db.models._auth import Tenant, User, UserTenantMembership

    tenant = Tenant(display_name="d")
    user = User(username="alice", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()

    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    await session.flush()
    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_orphan_membership_rejected_by_fk(session) -> None:
    from sqlalchemy.exc import IntegrityError

    from novamoc.db.models._auth import UserTenantMembership

    session.add(
        UserTenantMembership(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4()
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
```

Create `tests/accounts/test_membership_service.py` — exercises the N:1 invariant:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_tenant


async def _make_user_and_two_tenants(session):
    from novamoc.db.models._auth import Tenant, User

    user = User(username="alice", password_hash="x")
    tenant_a = Tenant(display_name="A")
    tenant_b = Tenant(display_name="B")
    session.add_all([user, tenant_a, tenant_b])
    await session.flush()
    return user, tenant_a, tenant_b


async def test_first_membership_succeeds(session) -> None:
    from novamoc.domain.accounts._services import UserTenantMembershipService

    user, tenant_a, _ = await _make_user_and_two_tenants(session)
    service = UserTenantMembershipService(session=session)
    membership = await service.create(
        {"user_id": user.id, "tenant_id": tenant_a.id}
    )
    assert membership.tenant_id == tenant_a.id


async def test_second_membership_for_same_user_rejected(session) -> None:
    from novamoc.domain.accounts._errors import UserAlreadyHasTenantError
    from novamoc.domain.accounts._services import UserTenantMembershipService

    user, tenant_a, tenant_b = await _make_user_and_two_tenants(session)
    service = UserTenantMembershipService(session=session)
    await service.create({"user_id": user.id, "tenant_id": tenant_a.id})
    with pytest.raises(UserAlreadyHasTenantError):
        await service.create({"user_id": user.id, "tenant_id": tenant_b.id})


async def test_membership_redo_after_delete_succeeds(session) -> None:
    """The invariant cares about live state, not history."""
    from novamoc.domain.accounts._services import UserTenantMembershipService

    user, tenant_a, _ = await _make_user_and_two_tenants(session)
    service = UserTenantMembershipService(session=session)
    membership = await service.create(
        {"user_id": user.id, "tenant_id": tenant_a.id}
    )
    await service.delete(item_id=(user.id, tenant_a.id))
    re_added = await service.create(
        {"user_id": user.id, "tenant_id": tenant_a.id}
    )
    assert re_added.user_id == user.id
```

(`UserAlreadyHasTenantError` is added in Step 4 below; Task 6 wires the corresponding `ErrorCode.USER_ALREADY_HAS_TENANT` and the problem-details mapper.)

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement `UserTenantMembership`**

Create `src/py/novamoc/db/models/_auth/_membership.py`:

```python
"""User ↔ Tenant membership (ADR-020).

Composite PK ``(user_id, tenant_id)`` doubles as the uniqueness
constraint. ``DefaultBase`` (not ``UUIDAuditBase``) because the
membership is a relation; its identity is the pair, not an opaque id.
v1 enforces one-membership-per-user at the service-layer write path
(see ``UserTenantMembershipService.create``) — the table allows N-to-N
from day one so future "switch active tenant" is a relaxation of the
service check, not a schema migration.
"""

from __future__ import annotations

import uuid

from advanced_alchemy.base import DefaultBase
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class UserTenantMembership(DefaultBase):
    __tablename__ = "user_tenant_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), primary_key=True
    )
```

Update `_auth/__init__.py` to re-export.

- [ ] **Step 4: Add `UserAlreadyHasTenantError`**

Append to `src/py/novamoc/domain/accounts/_errors.py`:

```python
class UserAlreadyHasTenantError(Exception):
    """Raised by UserTenantMembershipService.create when the user already
    has a membership. Maps to 409 ``user_already_has_tenant``.

    Lands here in Task 4 as a bare Exception so the service can raise it;
    Task 6 promotes it to a ``DomainError`` subclass with the ``ErrorCode``
    plumbing and the problem-details mapper.
    """
```

(The bare-Exception → DomainError promotion in Task 6 is a minor refactor; the tests in this task only depend on the type identity.)

- [ ] **Step 5: Implement `UserTenantMembershipService`**

Append to `_services.py`:

```python
import uuid

from novamoc.db.models._auth import UserTenantMembership
from novamoc.domain.accounts._errors import UserAlreadyHasTenantError


class UserTenantMembershipService(SQLAlchemyAsyncRepositoryService[UserTenantMembership]):
    class Repo(SQLAlchemyAsyncRepositoryService[UserTenantMembership].repository_type):
        model_type = UserTenantMembership

    repository_type = Repo

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserTenantMembership]:
        return await self.list(user_id=user_id)

    async def get_for_user(self, user_id: uuid.UUID) -> UserTenantMembership | None:
        """Return the single membership for ``user_id`` or None.

        Relies on the v1 N:1 invariant — if more than one row exists,
        that's a precondition violation and this method returns the
        first row deterministically; the alternative would be to raise,
        which complicates callers for an invariant that's already
        write-time-enforced.
        """
        rows = await self.list_for_user(user_id)
        return rows[0] if rows else None

    async def create(self, data, **kwargs):
        if isinstance(data, dict):
            user_id = data.get("user_id")
            if user_id is not None and await self.list_for_user(user_id):
                raise UserAlreadyHasTenantError
        return await super().create(data=data, **kwargs)
```

- [ ] **Step 6: Run the tests + full suite + lint + type-check**

Expected: all green. Note: SQLite enforces FK constraints only when `PRAGMA foreign_keys=ON`; the orphan-rejection test confirms the test harness has FK enforcement on.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/db/models/_auth/ \
        src/py/novamoc/domain/accounts/_services.py \
        src/py/novamoc/domain/accounts/_errors.py \
        tests/accounts/test_membership_model.py \
        tests/accounts/test_membership_service.py
git commit -m "feat(accounts): UserTenantMembership model + service; N:1 invariant at write time"
```

---

## Task 5: Password hashing module + unit tests

**Files:**
- Create: `src/py/novamoc/domain/accounts/_password.py`
- Create: `tests/accounts/test_password.py`

`_password.py` exposes a single `PasswordHasher` configured with settings-driven cost parameters. Storing the hasher on `app.state` happens in Task 11 (asgi wiring); this task ships the module + tests.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_password.py`:

```python
from __future__ import annotations

import pytest


def test_hash_and_verify_round_trip() -> None:
    from novamoc.domain.accounts._password import PasswordHasher

    hasher = PasswordHasher.from_defaults()
    encoded = hasher.hash("correct horse battery staple")
    assert hasher.verify(encoded, "correct horse battery staple") is True


def test_verify_rejects_wrong_password() -> None:
    from novamoc.domain.accounts._password import PasswordHasher

    hasher = PasswordHasher.from_defaults()
    encoded = hasher.hash("correct password")
    assert hasher.verify(encoded, "wrong password") is False


def test_hash_is_salted() -> None:
    from novamoc.domain.accounts._password import PasswordHasher

    hasher = PasswordHasher.from_defaults()
    a = hasher.hash("password")
    b = hasher.hash("password")
    assert a != b  # distinct salts


def test_check_needs_rehash_returns_true_after_cost_bump() -> None:
    from novamoc.domain.accounts._password import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost_kib=8, parallelism=1)
    strong = PasswordHasher(time_cost=3, memory_cost_kib=65536, parallelism=4)
    encoded = weak.hash("password")
    assert strong.check_needs_rehash(encoded) is True
    assert weak.check_needs_rehash(weak.hash("password")) is False


def test_verify_rejects_malformed_hash() -> None:
    from novamoc.domain.accounts._password import PasswordHasher

    hasher = PasswordHasher.from_defaults()
    assert hasher.verify("not-a-real-hash", "password") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/accounts/test_password.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `PasswordHasher`**

Create `src/py/novamoc/domain/accounts/_password.py`:

```python
"""Argon2id password hashing.

Thin wrapper over ``argon2.PasswordHasher`` that (a) folds verify failures
into a boolean return value rather than exceptions, so callers do not
branch on exception types for the binary outcome, and (b) carries the
cost parameters explicitly so settings-driven tuning is a constructor
arg, not module-global state.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# OWASP / RFC 9106 defaults for argon2id as of 2026.
_DEFAULT_TIME_COST = 3
_DEFAULT_MEMORY_COST_KIB = 64 * 1024  # 64 MiB
_DEFAULT_PARALLELISM = 4


@dataclass(frozen=True, slots=True)
class PasswordHasher:
    time_cost: int = _DEFAULT_TIME_COST
    memory_cost_kib: int = _DEFAULT_MEMORY_COST_KIB
    parallelism: int = _DEFAULT_PARALLELISM

    @classmethod
    def from_defaults(cls) -> PasswordHasher:
        return cls()

    @property
    def _impl(self) -> _Argon2Hasher:
        return _Argon2Hasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost_kib,
            parallelism=self.parallelism,
        )

    def hash(self, password: str) -> str:
        return self._impl.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._impl.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def check_needs_rehash(self, encoded: str) -> bool:
        try:
            return self._impl.check_needs_rehash(encoded)
        except InvalidHashError:
            return True
```

- [ ] **Step 4: Run the tests + full suite + lint + type-check**

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/accounts/_password.py \
        tests/accounts/test_password.py
git commit -m "feat(accounts): PasswordHasher wraps argon2-cffi with settings-driven costs"
```

---

## Task 6: `AuthSettings` (no dev-seed), error code promotions, problem-details mappers

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `src/py/novamoc/domain/_errors.py`
- Modify: `src/py/novamoc/domain/accounts/_errors.py` — promote `UserAlreadyHasTenantError` from bare Exception to a `DomainError` subclass; add `LoginFailedError`.
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `tests/api/test_problem_details.py`

The error codes + their wire-shape mappers land before the handlers (Task 10) so the handlers have somewhere to raise into.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_problem_details.py`:

```python
def test_login_failed_renders_401() -> None:
    from novamoc.api._problem_details import schema_error_to_problem_details
    from novamoc.domain.accounts._errors import LoginFailedError

    exc = LoginFailedError()
    pd = schema_error_to_problem_details(exc)
    assert pd.status_code == 401
    assert pd.type_ == "urn:novamoc:problems:login_failed"
    assert pd.title == "Login failed"
    # Anti-enumeration: detail must be generic, not "wrong password" / "no such user"
    assert "password" not in pd.detail.lower()
    assert "username" not in pd.detail.lower()


def test_user_already_has_tenant_renders_409() -> None:
    from novamoc.api._problem_details import schema_error_to_problem_details
    from novamoc.domain.accounts._errors import UserAlreadyHasTenantError

    exc = UserAlreadyHasTenantError()
    pd = schema_error_to_problem_details(exc)
    assert pd.status_code == 409
    assert pd.type_ == "urn:novamoc:problems:user_already_has_tenant"
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL with `ImportError` / `AttributeError` (Task 4 added `UserAlreadyHasTenantError` as a bare Exception; it doesn't have the `DomainError` shape yet).

- [ ] **Step 3: Add the error codes**

Edit `src/py/novamoc/domain/_errors.py` (or wherever `ErrorCode` lives — see existing references for the canonical path). Append to `ErrorCode`:

```python
LOGIN_FAILED = "login_failed"
USER_ALREADY_HAS_TENANT = "user_already_has_tenant"
```

Edit `src/py/novamoc/domain/accounts/_errors.py`. Replace the bare-Exception `UserAlreadyHasTenantError` from Task 4 with the DomainError version; add `LoginFailedError`:

```python
from novamoc.domain._errors import DomainError, ErrorCode


class LoginFailedError(DomainError):
    code = ErrorCode.LOGIN_FAILED
    status_code = 401
    default_message = "The provided credentials were not accepted."


class UserAlreadyHasTenantError(DomainError):
    code = ErrorCode.USER_ALREADY_HAS_TENANT
    status_code = 409
    default_message = (
        "This user already belongs to a tenant. v1 supports only one "
        "tenant per user; switching active tenant is not yet available."
    )
```

(Exact `DomainError` API matches whatever the existing schema errors use; replicate the shape from `domain/schema/_errors.py`.)

Edit `src/py/novamoc/api/_problem_details.py`. Append rows to `_TITLES`:

```python
ErrorCode.LOGIN_FAILED: "Login failed",
ErrorCode.USER_ALREADY_HAS_TENANT: "User already has a tenant",
```

And to `_STATUS_CODES`:

```python
ErrorCode.LOGIN_FAILED: 401,
ErrorCode.USER_ALREADY_HAS_TENANT: 409,
```

If `schema_error_to_problem_details` already routes by `ErrorCode`, no further wiring needed. Otherwise extend the converter.

- [ ] **Step 4: Add `AuthSettings`**

Edit `src/py/novamoc/config.py`. Add the new dataclass and field:

```python
@dataclass(frozen=True, slots=True)
class AuthSettings:
    session_ttl_seconds: int = field(
        default_factory=lambda: int(os.environ.get("NOVAMOC_AUTH_SESSION_TTL_SECONDS", "86400"))
    )
    session_cookie_name: str = field(
        default_factory=_str_env("NOVAMOC_AUTH_SESSION_COOKIE_NAME", "novamoc_session")
    )
    session_cookie_secure: bool = field(
        default_factory=_bool_env("NOVAMOC_AUTH_SESSION_COOKIE_SECURE", False)
    )
    argon2_time_cost: int = field(
        default_factory=lambda: int(os.environ.get("NOVAMOC_AUTH_ARGON2_TIME_COST", "3"))
    )
    argon2_memory_cost_kib: int = field(
        default_factory=lambda: int(os.environ.get("NOVAMOC_AUTH_ARGON2_MEMORY_COST_KIB", str(64 * 1024)))
    )
    argon2_parallelism: int = field(
        default_factory=lambda: int(os.environ.get("NOVAMOC_AUTH_ARGON2_PARALLELISM", "4"))
    )
```

Add `auth: AuthSettings = field(default_factory=AuthSettings)` to `Settings`.

**No `dev_seed_default_admin`, no `NOVAMOC_DEV_SEED_DEFAULT_ADMIN`** — the server has no environment-conditional code.

- [ ] **Step 5: Update the Task 4 service test**

The membership-service test in Task 4 expects `UserAlreadyHasTenantError` to be raisable. After this task it's a `DomainError` subclass; the test still passes (the type identity is what matters), but verify:

```bash
uv run pytest tests/accounts/test_membership_service.py -v
```

- [ ] **Step 6: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/py/novamoc/config.py \
        src/py/novamoc/domain/_errors.py \
        src/py/novamoc/domain/accounts/_errors.py \
        src/py/novamoc/api/_problem_details.py \
        tests/api/test_problem_details.py
git commit -m "feat(accounts): AuthSettings + LoginFailedError + UserAlreadyHasTenantError as DomainErrors"
```

---

## Task 7: `Session` model via advanced-alchemy backend; session middleware wiring scaffold

**Files:**
- Create: `src/py/novamoc/db/models/_auth/_session.py`
- Modify: `src/py/novamoc/db/models/_auth/__init__.py`
- Create: `tests/accounts/test_session_model.py`

The session mixin from advanced-alchemy provides the columns; we declare the model so it joins our metadata registry.

- [ ] **Step 1: Write the failing test**

Create `tests/accounts/test_session_model.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.no_tenant


async def test_session_row_inserts(session) -> None:
    from novamoc.db.models._auth import Session

    row = Session(
        session_id="abc123",
        data=b'{"user_id":"x","active_tenant_id":"dev"}',
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(row)
    await session.flush()
    assert row.id is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement the `Session` model**

Check advanced-alchemy's current API for the SQLAlchemy session backend's mixin class. As of the current release the pattern is:

```python
# src/py/novamoc/db/models/_auth/_session.py
"""Server-side session storage (ADR-020).

Backed by advanced-alchemy's ``SQLAlchemyAsyncSessionBackend`` mixin —
this is the same mixin Litestar's ``ServerSideSessionConfig`` will read
sessions from at request time. Storing sessions in the same database as
everything else is the v1 trade-off the spec settled on: no separate
Redis dependency.
"""

from __future__ import annotations

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.extensions.litestar.plugins.init.config.sqlalchemy import (
    SQLAlchemyAsyncSessionBackend,
)

# Layering note: this import does NOT pull Litestar into db-layer code at
# import time — advanced_alchemy.extensions.litestar's session backend is
# storage-tier even though its package path is under "extensions.litestar".
# If the layering check below ever blocks this import, treat it as the
# signal that advanced-alchemy reorganized; the model relocates to
# `domain/accounts/` and `db/models/_auth/__init__.py` re-exports it.


class Session(SQLAlchemyAsyncSessionBackend.session_model_mixin(), DefaultBase):
    __tablename__ = "sessions"
```

(If the mixin's exact name differs, follow advanced-alchemy's "session model" reference in their Litestar integration docs. The above is the shape; the import path may need adjustment.)

Update `_auth/__init__.py`:

```python
from novamoc.db.models._auth._membership import UserTenantMembership
from novamoc.db.models._auth._session import Session
from novamoc.db.models._auth._tenant import Tenant
from novamoc.db.models._auth._user import User

__all__ = ("Session", "Tenant", "User", "UserTenantMembership")
```

- [ ] **Step 4: Verify the layering rule still holds**

The "db/ must not depend on Litestar" rule in CLAUDE.md cares about `advanced_alchemy.extensions.litestar` imports in `db/`. The session-backend mixin's import path nominally violates this. Two acceptable resolutions, in order:

1. If advanced-alchemy exposes the mixin from a non-`extensions.litestar` path, prefer that.
2. If not, the session model is the lone exception — document it inline in `_session.py` with a comment and add an entry to CLAUDE.md's "Critical layering rule" section noting the exception. This is the call to flag explicitly during review.

- [ ] **Step 5: Run the tests + full suite + lint + type-check**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/models/_auth/_session.py \
        src/py/novamoc/db/models/_auth/__init__.py \
        tests/accounts/test_session_model.py
git commit -m "feat(accounts): Session model via advanced-alchemy backend mixin"
```

---

## Task 8: `Principal` struct + new payload structs

**Files:**
- Create: `src/py/novamoc/domain/accounts/_principal.py`
- Create: `src/py/novamoc/domain/accounts/_payloads.py`
- Create: `tests/accounts/test_principal.py`
- Create: `tests/accounts/test_payloads.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_principal.py`:

```python
from __future__ import annotations

import pytest


def test_principal_holds_id_and_username() -> None:
    from novamoc.domain.accounts._principal import Principal

    p = Principal(id="abc", username="alice")
    assert p.id == "abc"
    assert p.username == "alice"


def test_principal_is_frozen() -> None:
    from novamoc.domain.accounts._principal import Principal

    p = Principal(id="abc", username="alice")
    with pytest.raises(AttributeError):
        p.username = "bob"  # ty: ignore[unresolved-attribute]
```

Create `tests/accounts/test_payloads.py`:

```python
from __future__ import annotations

import pytest


def test_login_request_decodes_minimal_body() -> None:
    import msgspec

    from novamoc.domain.accounts._payloads import LoginRequest

    req = msgspec.json.decode(b'{"username":"alice","password":"pw"}', type=LoginRequest)
    assert req.username == "alice"
    assert req.password == "pw"


def test_login_request_rejects_extra_fields() -> None:
    import msgspec

    from novamoc.domain.accounts._payloads import LoginRequest

    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(b'{"username":"a","password":"p","extra":1}', type=LoginRequest)


def test_me_response_round_trips() -> None:
    import msgspec

    from novamoc.domain.accounts._payloads import MePrincipal, MeResponse, MeTenant

    resp = MeResponse(
        user=MePrincipal(id="01HX", username="alice"),
        tenant=MeTenant(id="dev", display_name="Development"),
    )
    encoded = msgspec.json.encode(resp)
    decoded = msgspec.json.decode(encoded, type=MeResponse)
    assert decoded == resp
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement `Principal`**

Create `src/py/novamoc/domain/accounts/_principal.py`:

```python
"""Per-request principal.

Lands on ``scope["user"]``; ADR-017's principal/scope split holds — the
principal is stable across requests, the scope (``RequestAuth``) varies.
Deliberately minimal: no password hash, no membership list, no audit
columns. Handlers that need more pull it from DI; the struct exists to
be cheap, immutable, and free of ORM-session attachment.
"""

from __future__ import annotations

import msgspec


class Principal(msgspec.Struct, frozen=True):
    id: str
    username: str
```

- [ ] **Step 4: Implement `_payloads.py`**

Create `src/py/novamoc/domain/accounts/_payloads.py`:

```python
"""Wire payloads for the auth endpoints.

``LoginRequest`` uses ``forbid_unknown_fields=True`` so accidental extras
fail loud (matches the spec's 400 ``invalid_payload_shape`` outcome).
``MeResponse`` is the canonical "who am I" probe; SPA reads it after
login and on each app boot.
"""

from __future__ import annotations

import msgspec


class LoginRequest(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    username: str
    password: str


class MePrincipal(msgspec.Struct, frozen=True):
    id: str
    username: str


class MeTenant(msgspec.Struct, frozen=True):
    id: str
    display_name: str


class MeResponse(msgspec.Struct, frozen=True):
    user: MePrincipal
    tenant: MeTenant
```

- [ ] **Step 5: Run the tests + full suite + lint + type-check**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/domain/accounts/_principal.py \
        src/py/novamoc/domain/accounts/_payloads.py \
        tests/accounts/test_principal.py \
        tests/accounts/test_payloads.py
git commit -m "feat(accounts): Principal + login/me payload structs"
```

---

## Task 9: REMOVED — no in-server seeder

The previous revision of this plan had a `seed_default_admin` task here. It has been removed: the server has no environment-conditional code, no startup hook, and no `dev_seed_default_admin` setting. Dev bootstrap is via CLI in every environment (see Task 13 for the CLI itself and Task 15 for the `just bootstrap-dev` recipe that wraps the three-command sequence). Task numbering is preserved so commit messages and PR comments referencing earlier numbers still resolve.

---

## Task 10: `login` / `logout` / `me` handlers + `AuthController`

**Files:**
- Create: `src/py/novamoc/domain/accounts/_handlers.py`
- Create: `src/py/novamoc/domain/accounts/controllers/__init__.py`
- Create: `src/py/novamoc/domain/accounts/controllers/_auth.py`

The handlers do not exercise the wider middleware stack — Task 11 (asgi wiring) does that. This task lands the route handlers in isolation; e2e tests come in Task 12 with the full wiring.

- [ ] **Step 1: Implement the handlers**

Create `src/py/novamoc/domain/accounts/_handlers.py`:

```python
"""POST /auth/login, POST /auth/logout, GET /auth/me handlers.

The login handler is the only one that writes the session; logout
clears it; me reads it. All three rely on the session cookie middleware
that ``asgi.create_app`` mounts upstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.db.models._auth import Tenant
from novamoc.domain.accounts._errors import LoginFailedError
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._payloads import (
    LoginRequest,
    MePrincipal,
    MeResponse,
    MeTenant,
)

if TYPE_CHECKING:
    from litestar import Request

    from novamoc.config import AuthSettings
    from novamoc.domain.accounts._principal import Principal
    from novamoc.domain.accounts._services import (
        TenantService,
        UserService,
        UserTenantMembershipService,
    )


async def login(
    data: LoginRequest,
    request: Request,
    auth_settings: AuthSettings,
    users: UserService,
    memberships: UserTenantMembershipService,
    password_hasher: PasswordHasher,
) -> None:
    user = await users.get_by_username(data.username)
    if user is None or user.disabled_at is not None:
        raise LoginFailedError
    if not password_hasher.verify(user.password_hash, data.password):
        raise LoginFailedError

    # N:1 invariant is enforced at UserTenantMembershipService.create
    # (Task 4), so by the time login runs, the user has 0 or 1 membership.
    # 0 means a stale invariant-violation; treat as login_failed.
    membership = await memberships.get_for_user(user.id)
    if membership is None:
        raise LoginFailedError
    active_tenant_id = membership.tenant_id

    # Rehash on cost change — free upgrade for the active user.
    if password_hasher.check_needs_rehash(user.password_hash):
        await users.update(
            {"password_hash": password_hasher.hash(data.password)},
            item_id=user.id,
        )

    request.set_session({"user_id": str(user.id), "active_tenant_id": str(active_tenant_id)})


async def logout(request: Request) -> None:
    request.clear_session()


async def me(
    request: Request,
    tenants: TenantService,
) -> MeResponse:
    principal: Principal = request.user
    auth = request.auth
    tenant = await tenants.get_one_or_none(id=auth.tenant_id)
    if tenant is None:  # pragma: no cover — middleware would have rejected first
        raise LoginFailedError
    return MeResponse(
        user=MePrincipal(id=principal.id, username=principal.username),
        tenant=MeTenant(id=str(tenant.id), display_name=tenant.display_name),
    )
```

- [ ] **Step 2: Implement the controller**

Create `src/py/novamoc/domain/accounts/controllers/__init__.py`:

```python
from novamoc.domain.accounts.controllers._auth import AuthController

__all__ = ("AuthController",)
```

Create `src/py/novamoc/domain/accounts/controllers/_auth.py`:

```python
"""HTTP routes for authentication.

Mounted under ``/auth``. ``POST /auth/login`` is the only route on the
authentication middleware's exclude list — login itself cannot require
prior authentication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar.providers import create_service_dependencies
from litestar import Controller, Request, get, post, status_codes
from litestar.di import Provide

from novamoc.db.models._auth import Tenant, User, UserTenantMembership
from novamoc.domain.accounts._handlers import login as _login
from novamoc.domain.accounts._handlers import logout as _logout
from novamoc.domain.accounts._handlers import me as _me
from novamoc.domain.accounts._payloads import LoginRequest, MeResponse
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from novamoc.config import AuthSettings


def _provide_password_hasher(request: Request) -> PasswordHasher:
    return request.app.state.password_hasher


def _provide_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.settings.auth


class AuthController(Controller):
    path = "/auth"
    dependencies = {
        **create_service_dependencies(
            User, service_class=UserService, key="users"
        ),
        **create_service_dependencies(
            UserTenantMembership, service_class=UserTenantMembershipService, key="memberships"
        ),
        **create_service_dependencies(
            Tenant, service_class=TenantService, key="tenants"
        ),
        "password_hasher": Provide(_provide_password_hasher, sync_to_thread=False),
        "auth_settings": Provide(_provide_auth_settings, sync_to_thread=False),
    }

    @post("/login", status_code=status_codes.HTTP_204_NO_CONTENT)
    async def login(
        self,
        data: LoginRequest,
        request: Request,
        auth_settings: "AuthSettings",
        users: UserService,
        memberships: UserTenantMembershipService,
        password_hasher: PasswordHasher,
    ) -> None:
        await _login(
            data=data,
            request=request,
            auth_settings=auth_settings,
            users=users,
            memberships=memberships,
            password_hasher=password_hasher,
        )

    @post("/logout", status_code=status_codes.HTTP_204_NO_CONTENT)
    async def logout(self, request: Request) -> None:
        await _logout(request=request)

    @get("/me")
    async def me(self, request: Request, tenants: TenantService) -> MeResponse:
        return await _me(request=request, tenants=tenants)
```

(The exact `advanced_alchemy.extensions.litestar.providers.create_service_dependencies` invocation depends on the repo's existing controllers — match the schema controller's pattern under `domain/schema/controllers/_schema.py`.)

- [ ] **Step 3: Run the test suite to confirm no regression**

```bash
uv run pytest
```

Expected: no tests for the controller exist yet (Task 12 adds e2e tests). The full suite stays green; new modules are not yet imported by `asgi.py`.

- [ ] **Step 4: Lint and type-check**

```bash
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/accounts/_handlers.py \
        src/py/novamoc/domain/accounts/controllers/
git commit -m "feat(accounts): login/logout/me handlers + AuthController"
```

---

## Task 11: Rewrite resolver + middleware; wire everything in `asgi.py`

**Files (10 — exceeds the per-task heuristic):**
- Modify: `src/py/novamoc/domain/accounts/_resolver.py`
- Modify: `src/py/novamoc/domain/accounts/_middleware.py`
- Modify: `src/py/novamoc/domain/accounts/__init__.py`
- Modify: `src/py/novamoc/asgi.py`
- Modify: `src/py/novamoc/db/_listeners.py`
- Create: `tests/accounts/test_resolver_session.py`
- Modify: `tests/conftest.py` — preview fixture wiring (full migration in Task 12).

**Rationale for the file count:** the resolver rewrite, the middleware async update, and the asgi-level wiring (session middleware mount, problem-details mappers, hasher on state, before_startup seed hook, `AuthController` registration) are one conceptual seam. Splitting them would leave the working tree in a state where `AuthenticationMiddleware` is async but neither the new session middleware nor the auth controller are mounted — an intermediate state where the existing schema tests can't pass. The single-task swap keeps the working tree green at the boundary.

- [ ] **Step 1: Write the failing resolver tests**

Create `tests/accounts/test_resolver_session.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_tenant


async def test_resolve_principal_returns_user_and_auth(session, dev_admin) -> None:
    from novamoc.domain.accounts._principal import Principal
    from novamoc.domain.accounts._auth import RequestAuth
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )
    from tests._constants import DEV_TENANT_ID

    user = await UserService(session=session).get_by_username("admin")

    principal, auth = await resolve_principal_from_session(
        session_payload={"user_id": str(user.id), "active_tenant_id": str(DEV_TENANT_ID)},
        users=UserService(session=session),
        memberships=UserTenantMembershipService(session=session),
    )

    assert isinstance(principal, Principal)
    assert principal.username == "admin"
    assert auth == RequestAuth(tenant_id=DEV_TENANT_ID)


async def test_missing_session_keys_raises(session) -> None:
    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    for payload in ({}, {"user_id": "x"}, {"active_tenant_id": "irrelevant"}):
        with pytest.raises(TenantResolutionError):
            await resolve_principal_from_session(
                session_payload=payload,
                users=UserService(session=session),
                memberships=UserTenantMembershipService(session=session),
            )


async def test_unknown_user_raises(session) -> None:
    import uuid

    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            session_payload={"user_id": str(uuid.uuid4()), "active_tenant_id": str(uuid.uuid4())},
            users=UserService(session=session),
            memberships=UserTenantMembershipService(session=session),
        )


async def test_disabled_user_raises(session, dev_admin) -> None:
    from datetime import UTC, datetime

    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )
    from tests._constants import DEV_TENANT_ID

    users = UserService(session=session)
    user = await users.get_by_username("admin")
    await users.update({"disabled_at": datetime.now(UTC)}, item_id=user.id)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            session_payload={"user_id": str(user.id), "active_tenant_id": str(DEV_TENANT_ID)},
            users=users,
            memberships=UserTenantMembershipService(session=session),
        )


async def test_missing_membership_raises(session, dev_admin) -> None:
    import uuid

    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    user = await UserService(session=session).get_by_username("admin")

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            session_payload={
                "user_id": str(user.id),
                "active_tenant_id": str(uuid.uuid4()),  # tenant they have no membership in
            },
            users=UserService(session=session),
            memberships=UserTenantMembershipService(session=session),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Rewrite `_resolver.py`**

Replace `src/py/novamoc/domain/accounts/_resolver.py` with:

```python
"""Tenant resolution from the request envelope.

v2 (ADR-020): the credential is a server-side session cookie. The
``SessionMiddleware`` populates ``connection.session`` upstream; this
module reads the session payload, looks up the user and active
membership, and returns a frozen ``(Principal, RequestAuth)`` tuple.

The middleware that calls this function lives in ``_middleware.py``;
keeping the resolver pure (no Litestar imports beyond the type hint)
preserves ADR-017's swap-point property — the next credential change
will replace this module alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import TenantResolutionError
from novamoc.domain.accounts._principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )


async def resolve_principal_from_session(
    session_payload: Mapping[str, Any],
    users: UserService,
    memberships: UserTenantMembershipService,
) -> tuple[Principal, RequestAuth]:
    """Return ``(Principal, RequestAuth)`` for this session, or raise.

    Raises:
        TenantResolutionError: when the session is missing the expected
            keys, the user does not exist or is disabled, or the user's
            membership for the active tenant is missing.
    """
    user_id = session_payload.get("user_id")
    active_tenant_id = session_payload.get("active_tenant_id")
    if not user_id or not active_tenant_id:
        raise TenantResolutionError

    user = await users.get_one_or_none(id=user_id)
    if user is None or user.disabled_at is not None:
        raise TenantResolutionError

    membership = await memberships.get_one_or_none(
        user_id=user.id, tenant_id=active_tenant_id
    )
    if membership is None:
        raise TenantResolutionError

    return (
        Principal(id=str(user.id), username=user.username),
        RequestAuth(tenant_id=uuid.UUID(active_tenant_id) if isinstance(active_tenant_id, str) else active_tenant_id),
    )
```

- [ ] **Step 4: Rewrite `_middleware.py`'s `authenticate_request`**

Edit `src/py/novamoc/domain/accounts/_middleware.py`. Replace the import block and the class body:

```python
"""Authentication middleware that resolves the per-request RequestAuth + Principal.

v2 (ADR-020): reads ``connection.session`` (populated upstream by the
server-side session middleware) and looks up the user + active tenant
via the request-scoped SQLAlchemy session. The resolver itself is in
``_resolver.py``; this module wires it to Litestar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
)
from litestar.middleware import ASGIMiddleware
from litestar.middleware.authentication import (
    AbstractAuthenticationMiddleware,
    AuthenticationResult,
)

from novamoc.db._tenant_context import use_tenant
from novamoc.domain.accounts._resolver import resolve_principal_from_session
from novamoc.domain.accounts._services import (
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection
    from litestar.types import ASGIApp, Receive, Scope, Send


class AuthenticationMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        alchemy_config: SQLAlchemyAsyncConfig = connection.app.plugins.get(
            "SQLAlchemyPlugin"
        ).config  # type: ignore[attr-defined]
        async with alchemy_config.get_session() as db_session:
            principal, auth = await resolve_principal_from_session(
                session_payload=connection.session,
                users=UserService(session=db_session),
                memberships=UserTenantMembershipService(session=db_session),
            )
        return AuthenticationResult(user=principal, auth=auth)


class TenantContextMiddleware(ASGIMiddleware):
    """Bind the per-request RequestAuth.tenant_id to the storage-layer ContextVar.

    Unchanged from v1.
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
        with use_tenant(auth.tenant_id):
            await next_app(scope, receive, send)
```

(The exact path to grab the request-scoped SQLAlchemy session may need tweaking — `connection.app.plugins.get("SQLAlchemyPlugin").config.get_session()` is the shape; the repo's existing DI providers under `domain/schema/controllers/_schema.py` show the canonical access pattern.)

- [ ] **Step 5: Update `accounts/__init__.py` re-exports**

```python
from novamoc.domain.accounts._auth import RequestAuth
from novamoc.domain.accounts._errors import (
    LoginFailedError,
    TenantResolutionError,
    UserAlreadyHasTenantError,
)
from novamoc.domain.accounts._middleware import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
)
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._principal import Principal
from novamoc.domain.accounts.controllers import AuthController

__all__ = (
    "AuthController",
    "AuthenticationMiddleware",
    "LoginFailedError",
    "PasswordHasher",
    "Principal",
    "RequestAuth",
    "TenantContextMiddleware",
    "TenantResolutionError",
    "UserAlreadyHasTenantError",
)
```

- [ ] **Step 6: Wire `asgi.py`**

Edit `src/py/novamoc/asgi.py`:

1. Import the new pieces:

```python
from advanced_alchemy.extensions.litestar.plugins.init.config.sqlalchemy import (
    SQLAlchemyAsyncSessionBackend,
)
from litestar.middleware.session.server_side import ServerSideSessionConfig

from novamoc.api._problem_details import (
    make_login_failed_error_converter,
    make_user_already_has_tenant_error_converter,
    # ... existing imports
)
from novamoc.domain.accounts import (
    AuthController,
    AuthenticationMiddleware,
    LoginFailedError,
    PasswordHasher,
    TenantContextMiddleware,
    TenantResolutionError,
    UserAlreadyHasTenantError,
)
```

(No `seed_default_admin` import — there is no seed function.)

2. Build the server-side session config from the alchemy config + auth settings:

```python
session_backend = SQLAlchemyAsyncSessionBackend(alchemy_config=alchemy_config)
session_config = ServerSideSessionConfig(
    backend=session_backend,
    max_age=s.auth.session_ttl_seconds,
    key=s.auth.session_cookie_name,
    secure=s.auth.session_cookie_secure,
    httponly=True,
    samesite="lax",
    path="/",
)
```

3. Add the new error converters to the problem-details map:

```python
exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
    DomainError: make_domain_error_converter(base_url),
    TenantResolutionError: make_tenant_resolution_error_converter(base_url),
    LoginFailedError: make_login_failed_error_converter(base_url),
    UserAlreadyHasTenantError: make_user_already_has_tenant_error_converter(base_url),
    msgspec.ValidationError: make_msgspec_validation_error_converter(base_url),
    ValidationException: make_litestar_validation_error_converter(base_url),
},
```

(If the existing `make_domain_error_converter` already routes by `ErrorCode`, the two new lines collapse into it; double-check `api/_problem_details.py` for the actual converter shape.)

4. Mount the session middleware and update the auth middleware's exclude regex:

```python
middleware=[
    session_config.middleware,
    DefineMiddleware(
        AuthenticationMiddleware,
        exclude=r"^/(openapi|problems|auth/login)",
    ),
    TenantContextMiddleware(),
],
```

5. Register `AuthController`:

```python
route_handlers=[AuthController, SchemaController, EventsController, problem_docs_router],
```

6. Stash the password hasher on `app.state`:

```python
password_hasher = PasswordHasher(
    time_cost=s.auth.argon2_time_cost,
    memory_cost_kib=s.auth.argon2_memory_cost_kib,
    parallelism=s.auth.argon2_parallelism,
)

# ... in Litestar(...):
state=State({"settings": s, "password_hasher": password_hasher}),
```

**No `on_startup` hook for seeding** — the server has no environment-conditional code. Bootstrap is via CLI in every environment.

7. Add the problem-details factories in `api/_problem_details.py` if they don't already follow from `make_domain_error_converter`. If your existing converter dispatches on `ErrorCode`, no new factory is needed — `LoginFailedError` and `UserAlreadyHasTenantError` inherit from `DomainError` and just need the `_TITLES`/`_STATUS_CODES` rows from Task 6.

- [ ] **Step 7: Update the listener allow-list**

Edit `src/py/novamoc/db/_listeners.py`. Add a defensive allow-list pin:

```python
# Auth-layer tables explicitly excluded from tenant-scoping enforcement.
# The listeners' column-presence heuristic already handles this correctly
# (none of these tables carry a tenant_id column), but pinning the intent
# prevents future model changes from accidentally adding tenant_id and
# silently scoping these globally-unique tables.
_AUTH_LAYER_TABLE_NAMES = frozenset({
    "tenants",
    "users",
    "user_tenant_memberships",
    "sessions",
})
```

Reference `_AUTH_LAYER_TABLE_NAMES` in the relevant listener guard (assert-or-skip pattern depends on existing listener structure — match the style of the listeners that already do "is this synced?" checks).

- [ ] **Step 8: Migrate `conftest.py`**

The bootstrap path the test fixture uses is the same path `just bootstrap-dev` runs on the CLI — direct service calls against the test session. This keeps the test path environment-symmetric with production and removes any dependency on a startup hook (there is none).

Add a `dev_admin` fixture that creates the dev tenant + `admin` user + membership via direct service calls. The authenticated `client` fixture depends on `dev_admin` and logs in:

```python
import uuid
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService, UserService, UserTenantMembershipService,
)
from tests._constants import DEV_TENANT_ID


@pytest.fixture
async def dev_admin(session, settings):
    """Idempotently create the dev tenant + admin user + membership.

    This mirrors what ``just bootstrap-dev`` does on the CLI — same
    service calls, same write path, no server-side seed code.
    """
    hasher = PasswordHasher(
        time_cost=settings.auth.argon2_time_cost,
        memory_cost_kib=settings.auth.argon2_memory_cost_kib,
        parallelism=settings.auth.argon2_parallelism,
    )
    tenants = TenantService(session=session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    # Use a fixed UUID for the dev tenant so scenarios and the autouse
    # `tenant` fixture see the same value.
    existing = await tenants.get_one_or_none(id=DEV_TENANT_ID)
    if existing is None:
        await tenants.repository.add(
            tenants.repository.model_type(id=DEV_TENANT_ID, display_name="Development"),
        )
    if await users.get_by_username("admin") is None:
        user = await users.create(
            {"username": "admin", "password_hash": hasher.hash("admin")}
        )
        await memberships.create({"user_id": user.id, "tenant_id": DEV_TENANT_ID})
    await session.commit()


@pytest.fixture
async def client(app, dev_admin):
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login", json={"username": "admin", "password": "admin"}
        )
        assert resp.status_code == 204, resp.text
        yield c
```

The `unauth_client` fixture (added in Task 12) is structurally identical without the login call.

Note: the fixture creates the `Tenant` row with `id=DEV_TENANT_ID` rather than letting `UUIDAuditBase` generate one — this is the one place tests pin a specific UUID so scenarios can FK to it. The CLI never does this; it always lets the DB generate the UUID.

- [ ] **Step 9: Run the resolver tests + the full suite**

```bash
uv run pytest tests/accounts/test_resolver_session.py -v
uv run pytest
```

Expected: the new resolver tests pass; the existing schema/events e2e tests pass (they now log in at fixture setup); the unit handler tests under `tests/schema/test_handlers_*.py` continue to use `tenant_context` directly.

- [ ] **Step 10: Lint and type-check**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
just ratchet
```

Expected: all green; ratchet baselines unchanged or only decreasing.

- [ ] **Step 11: Commit**

```bash
git add src/py/novamoc/domain/accounts/ \
        src/py/novamoc/asgi.py \
        src/py/novamoc/db/_listeners.py \
        src/py/novamoc/api/_problem_details.py \
        tests/conftest.py \
        tests/accounts/test_resolver_session.py
git commit -m "feat(api): swap bearer resolver for session-backed Principal+RequestAuth"
```

---

## Task 12: e2e tests for `/auth/login`, `/auth/logout`, `/auth/me`; finalize conftest

**Files:**
- Create: `tests/accounts/test_login_e2e.py`
- Create: `tests/accounts/test_logout_e2e.py`
- Create: `tests/accounts/test_me_e2e.py`
- Modify: `tests/conftest.py` — add `unauth_client`, formalize fixture surface.

The auth endpoints are now reachable; pin their wire contracts.

- [ ] **Step 1: Add the `unauth_client` fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
async def unauth_client(app: Litestar):
    """An AsyncTestClient that has NOT logged in.

    For tests that exercise the 401 rejection path. Distinct from the
    autouse-authenticated ``client`` so each path is greppable.
    """
    async with AsyncTestClient(app) as c:
        yield c
```

- [ ] **Step 2: Write the login e2e tests**

Create `tests/accounts/test_login_e2e.py`:

```python
from __future__ import annotations

import pytest


async def test_valid_credentials_returns_204_with_session_cookie(unauth_client) -> None:
    resp = await unauth_client.post(
        "/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert resp.status_code == 204, resp.text
    cookie = resp.headers.get("set-cookie", "")
    assert "novamoc_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


async def test_wrong_password_returns_401_login_failed(unauth_client) -> None:
    resp = await unauth_client.post(
        "/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "urn:novamoc:problems:login_failed"


async def test_unknown_user_returns_401_login_failed(unauth_client) -> None:
    resp = await unauth_client.post(
        "/auth/login", json={"username": "ghost", "password": "anything"}
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "urn:novamoc:problems:login_failed"


async def test_wrong_password_and_unknown_user_indistinguishable(unauth_client) -> None:
    """Anti-enumeration: the two responses must match exactly."""
    wrong_pw = await unauth_client.post(
        "/auth/login", json={"username": "admin", "password": "wrong"}
    )
    unknown = await unauth_client.post(
        "/auth/login", json={"username": "ghost", "password": "anything"}
    )
    # Body equality (the ``instance`` UUID will differ; strip it for comparison).
    wp = {k: v for k, v in wrong_pw.json().items() if k != "instance"}
    un = {k: v for k, v in unknown.json().items() if k != "instance"}
    assert wp == un


async def test_missing_password_field_returns_400(unauth_client) -> None:
    resp = await unauth_client.post("/auth/login", json={"username": "admin"})
    assert resp.status_code == 400


async def test_extra_field_returns_400(unauth_client) -> None:
    resp = await unauth_client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin", "extra": "no"},
    )
    assert resp.status_code == 400


async def test_user_with_zero_memberships_returns_login_failed(unauth_client, app, session, dev_admin) -> None:
    """A user whose membership has been deleted out from under them
    (transient invariant violation) is rejected as login_failed —
    anti-enumeration with the other 401 cases."""
    from novamoc.domain.accounts._services import UserService, UserTenantMembershipService
    from sqlalchemy import delete
    from novamoc.db.models._auth import UserTenantMembership

    users = UserService(session=session)
    admin = await users.get_by_username("admin")
    await session.execute(
        delete(UserTenantMembership).where(UserTenantMembership.user_id == admin.id)
    )
    await session.commit()

    resp = await unauth_client.post(
        "/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert resp.status_code == 401
    assert resp.json()["type"] == "urn:novamoc:problems:login_failed"
```

The "user with two memberships → 409" case from the previous revision is gone: the N:1 invariant is enforced at write time (Task 4's `UserTenantMembershipService.create` test pins it), so it cannot arise at login. The CLI-side 409 surface is covered in Task 13.

- [ ] **Step 3: Write the logout + me e2e tests**

Create `tests/accounts/test_logout_e2e.py`:

```python
from __future__ import annotations


async def test_logout_clears_session_cookie(client) -> None:
    resp = await client.post("/auth/logout")
    assert resp.status_code == 204
    cookie = resp.headers.get("set-cookie", "")
    assert "novamoc_session=" in cookie
    assert "Max-Age=0" in cookie or "max-age=0" in cookie.lower()


async def test_after_logout_next_request_is_401(client) -> None:
    await client.post("/auth/logout")
    resp = await client.get("/schema")
    assert resp.status_code == 401


async def test_logout_without_session_is_401(unauth_client) -> None:
    resp = await unauth_client.post("/auth/logout")
    assert resp.status_code == 401
```

Create `tests/accounts/test_me_e2e.py`:

```python
from __future__ import annotations


async def test_me_returns_principal_and_tenant(client) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "admin"
    assert body["tenant"]["id"] == "dev"
    assert body["tenant"]["display_name"] == "Development"


async def test_me_unauthenticated_is_401(unauth_client) -> None:
    resp = await unauth_client.get("/auth/me")
    assert resp.status_code == 401
```

- [ ] **Step 4: Run the new tests + the full suite + lint + type-check + ratchet**

```bash
uv run pytest tests/accounts/ -v
uv run pytest
uv run ruff check src tests
uv run ty check
just ratchet
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/accounts/test_login_e2e.py \
        tests/accounts/test_logout_e2e.py \
        tests/accounts/test_me_e2e.py \
        tests/conftest.py
git commit -m "test(accounts): e2e coverage for login/logout/me + unauth_client fixture"
```

---

## Task 13: CLI commands

**Files:**
- Modify: `pyproject.toml` — declare the `novamoc` entry point.
- Create: `src/py/novamoc/cli.py`
- Create: `tests/accounts/test_cli.py`

Operator path for managing tenants and users without a web UI.

- [ ] **Step 1: Declare the entry point**

Append to `pyproject.toml`:

```toml
[project.scripts]
novamoc = "novamoc.cli:main"
```

Run `uv sync` to wire the script.

- [ ] **Step 2: Write the failing tests**

Create `tests/accounts/test_cli.py`:

```python
from __future__ import annotations

from click.testing import CliRunner


def test_tenant_create_succeeds(settings) -> None:
    from novamoc.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    assert result.exit_code == 0, result.output
    # Output includes the generated UUID for the new tenant — parse it.
    # The CLI prints "Created tenant <uuid>." on success.


def test_user_create_then_add_to_tenant(settings) -> None:
    """Happy path: create tenant, create user, add to tenant."""
    from novamoc.cli import main

    runner = CliRunner()
    r_tenant = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    assert r_tenant.exit_code == 0
    # Extract tenant UUID from CLI output.
    tenant_id = r_tenant.output.strip().split()[-1].rstrip(".")

    r_user = runner.invoke(main, ["user", "create", "bob", "--password", "bob-secret"])
    assert r_user.exit_code == 0, r_user.output

    r_add = runner.invoke(main, ["user", "add-to-tenant", "bob", tenant_id])
    assert r_add.exit_code == 0, r_add.output


def test_user_add_to_second_tenant_rejected(settings) -> None:
    """N:1 invariant: a user already in tenant A cannot be added to tenant B."""
    from novamoc.cli import main

    runner = CliRunner()
    r_a = runner.invoke(main, ["tenant", "create", "--display-name", "A"])
    tenant_a = r_a.output.strip().split()[-1].rstrip(".")
    r_b = runner.invoke(main, ["tenant", "create", "--display-name", "B"])
    tenant_b = r_b.output.strip().split()[-1].rstrip(".")

    runner.invoke(main, ["user", "create", "bob", "--password", "x"])
    runner.invoke(main, ["user", "add-to-tenant", "bob", tenant_a])

    result = runner.invoke(main, ["user", "add-to-tenant", "bob", tenant_b])
    assert result.exit_code != 0
    assert "already" in result.output.lower() and "tenant" in result.output.lower()


def test_user_set_password(settings) -> None:
    from novamoc.cli import main

    runner = CliRunner()
    runner.invoke(main, ["user", "create", "alice", "--password", "old"])
    result = runner.invoke(main, ["user", "set-password", "alice", "--password", "new"])
    assert result.exit_code == 0, result.output


def test_auth_gc_sessions_runs_clean(settings) -> None:
    from novamoc.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["auth", "gc-sessions"])
    assert result.exit_code == 0
    assert "deleted" in result.output.lower() or "sessions" in result.output.lower()
```

(The CLI tests need to run against a real database. The simplest path is a `tmp_path` fixture supplying a `NOVAMOC_DB_URL=sqlite+aiosqlite:///<tmp>/test.db` env var to each Click invocation; the `settings` fixture can pre-configure this. See existing tests for the env-var override pattern.)

- [ ] **Step 3: Implement the CLI**

Create `src/py/novamoc/cli.py`:

```python
"""Operator CLI for tenant + user + session management.

Mounted as the ``novamoc`` console script via ``[project.scripts]``.
Sub-commands share a single DB session per invocation, opened lazily,
committed on success, rolled back on failure.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import click

from novamoc.config import Settings
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import TypeVar

    T = TypeVar("T")


def _run(coro: "Awaitable[T]") -> "T":
    return asyncio.run(coro)


async def _session_context():
    """Build a single AsyncSession against the configured DB."""
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        EngineConfig,
        SQLAlchemyAsyncConfig,
    )

    s = Settings()
    config = SQLAlchemyAsyncConfig(
        connection_string=s.db.url,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        engine_config=EngineConfig(),
    )
    return s, config


@click.group()
def main() -> None:
    """novaMOC operator commands."""


@main.group()
def tenant() -> None:
    """Manage tenants."""


@tenant.command("create")
@click.option("--display-name", required=True)
def tenant_create(display_name: str) -> None:
    """Create a tenant. PK UUID is generated by the DB."""

    async def run() -> None:
        _settings, config = await _session_context()
        async with config.get_session() as session:
            try:
                tenant = await TenantService(session=session).create(
                    {"display_name": display_name}
                )
                await session.commit()
                click.echo(f"Created tenant {tenant.id}.")
            except Exception as exc:
                await session.rollback()
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)

    _run(run())


@main.group()
def user() -> None:
    """Manage users."""


@user.command("create")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=False)
def user_create(username: str, password: str) -> None:
    """Create a user with the given username and password."""

    async def run() -> None:
        settings, config = await _session_context()
        hasher = PasswordHasher(
            time_cost=settings.auth.argon2_time_cost,
            memory_cost_kib=settings.auth.argon2_memory_cost_kib,
            parallelism=settings.auth.argon2_parallelism,
        )
        async with config.get_session() as session:
            try:
                await UserService(session=session).create(
                    {"username": username, "password_hash": hasher.hash(password)}
                )
                await session.commit()
                click.echo(f"Created user '{username}'.")
            except Exception as exc:
                await session.rollback()
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)

    _run(run())


@user.command("set-password")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=False)
def user_set_password(username: str, password: str) -> None:
    async def run() -> None:
        settings, config = await _session_context()
        hasher = PasswordHasher(
            time_cost=settings.auth.argon2_time_cost,
            memory_cost_kib=settings.auth.argon2_memory_cost_kib,
            parallelism=settings.auth.argon2_parallelism,
        )
        async with config.get_session() as session:
            users = UserService(session=session)
            target = await users.get_by_username(username)
            if target is None:
                click.echo(f"User '{username}' not found.", err=True)
                sys.exit(1)
            await users.update({"password_hash": hasher.hash(password)}, item_id=target.id)
            await session.commit()
            click.echo(f"Password reset for '{username}'.")

    _run(run())


@user.command("add-to-tenant")
@click.argument("username")
@click.argument("tenant_id")
def user_add_to_tenant(username: str, tenant_id: str) -> None:
    """Add ``username`` to ``tenant_id`` (a UUID). Rejects if the user
    already has a tenant (v1 N:1 invariant)."""
    import uuid

    from novamoc.domain.accounts._errors import UserAlreadyHasTenantError

    async def run() -> None:
        _settings, config = await _session_context()
        try:
            target_tenant = uuid.UUID(tenant_id)
        except ValueError:
            click.echo(f"Error: {tenant_id!r} is not a valid UUID.", err=True)
            sys.exit(1)

        async with config.get_session() as session:
            users = UserService(session=session)
            target = await users.get_by_username(username)
            if target is None:
                click.echo(f"User {username!r} not found.", err=True)
                sys.exit(1)
            try:
                await UserTenantMembershipService(session=session).create(
                    {"user_id": target.id, "tenant_id": target_tenant}
                )
            except UserAlreadyHasTenantError:
                await session.rollback()
                click.echo(
                    f"Error: user {username!r} already has a tenant. "
                    "v1 supports only one tenant per user.",
                    err=True,
                )
                sys.exit(1)
            await session.commit()
            click.echo(f"Added {username!r} to tenant {target_tenant}.")

    _run(run())


@main.group()
def auth() -> None:
    """Auth-layer maintenance."""


@auth.command("gc-sessions")
def auth_gc_sessions() -> None:
    """Delete expired session rows."""

    async def run() -> None:
        from datetime import UTC, datetime

        from sqlalchemy import delete

        from novamoc.db.models._auth import Session

        _settings, config = await _session_context()
        async with config.get_session() as session:
            result = await session.execute(
                delete(Session).where(Session.expires_at < datetime.now(UTC))
            )
            await session.commit()
            click.echo(f"Deleted {result.rowcount} expired sessions.")

    _run(run())
```

- [ ] **Step 4: Run the CLI tests + the full suite**

Expected: all green.

- [ ] **Step 5: Lint and type-check**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock \
        src/py/novamoc/cli.py \
        tests/accounts/test_cli.py
git commit -m "feat(cli): novamoc tenant/user/auth commands"
```

---

## Task 14: Svelte login page

**Files:**
- Create: `src/js/web/src/routes/login/+page.svelte`
- Optionally modify: `src/js/web/src/routes/+layout.svelte` for the auth-gate check on app boot.

**REQUIRED:** Use the `svelte:svelte-file-editor` agent for all `.svelte` changes per CLAUDE.md. The agent invokes the Svelte MCP server's `svelte-autofixer` to catch Svelte 5 runes errors automatically.

The SPA is mostly scaffolding today. This task adds the minimum that exercises the auth surface end-to-end: a login form, a redirect on success, and a "current user" probe on layout mount. Anything beyond that is a separate UI milestone.

- [ ] **Step 1: Dispatch the svelte-file-editor agent**

Brief the agent:

> Create `src/js/web/src/routes/login/+page.svelte` — a minimal Svelte 5 login form. Two inputs (`username`, `password`), a submit button. On submit, `fetch('/auth/login', {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, password})})`. On 204, navigate to `/` via `goto()` from `$app/navigation`. On 4xx, surface the problem-details `title` and `detail` to the user. Use Svelte 5 runes (`$state`, `$derived`). Tailwind classes for styling — keep it deliberately minimal (no design polish; that's a separate milestone). Confirm with `mcp__svelte__svelte-autofixer` after writing and before reporting back.

The agent reports a path and a clean autofixer run.

- [ ] **Step 2: Add a layout-level "who am I" boot probe**

If `+layout.svelte` exists with scaffolding only: extend it to call `GET /auth/me` on mount. On 401, redirect to `/login`. On 200, stash the principal in a context or store. Keep the implementation small (under 30 lines).

- [ ] **Step 3: Verify the dev server builds**

```bash
cd src/js/web
npm run check  # svelte-check + tsc
```

Expected: no errors.

- [ ] **Step 4: Smoke test via Playwright OR manual browser check**

Per CLAUDE.md's UI-testing rule (verify in a browser before marking complete):

```bash
# One-time setup: bootstrap the dev admin via CLI.
just bootstrap-dev

# Terminal 1 — backend:
uv run litestar --app novamoc.asgi:create_app run

# Terminal 2 — frontend dev server:
cd src/js/web && npm run dev
```

Open the SPA, confirm the login page renders, submit `admin`/`admin`, confirm the redirect, confirm a follow-up `GET /auth/me` returns 200. Try `admin`/`wrong`; confirm the error is surfaced.

- [ ] **Step 5: Commit**

```bash
git add src/js/web/src/routes/login/
git commit -m "feat(web): minimal Svelte 5 login page + layout auth-gate"
```

---

## Task 15: `justfile` `bootstrap-dev` recipe + README + final verification

**Files:**
- Modify: `justfile` — add `bootstrap-dev` recipe.
- Modify: `README.md`

The bootstrap recipe is the canonical "fresh checkout to working dev login" command. It's the same sequence an operator would run in an init container in production — same CLI, same write path, no env-conditional code.

- [ ] **Step 1: Add the `bootstrap-dev` recipe**

Append to `justfile`:

```just
# Create the dev tenant + admin user. Idempotent: skips when admin exists.
# Production runs the equivalent in an init container.
bootstrap-dev:
    #!/usr/bin/env bash
    set -euo pipefail
    if uv run novamoc user exists admin >/dev/null 2>&1; then
        echo "admin user already exists; nothing to do."
        exit 0
    fi
    tenant_id=$(uv run novamoc tenant create --display-name "Development" | awk '{print $3}' | tr -d '.')
    echo "Created tenant $tenant_id."
    uv run novamoc user create admin --password admin
    uv run novamoc user add-to-tenant admin "$tenant_id"
    echo "Bootstrap complete. Login at /login with admin / admin."
```

(The `novamoc user exists` sub-command is a small addition to Task 13's CLI — exits 0 if the user exists, 1 if not. Add a one-line failing test and the implementation in Task 13's commit, OR fold it into this commit. The plan picks the latter to keep Task 13 focused on the four primary CLI commands.)

- [ ] **Step 2: Update `README.md`**

Replace the existing "Development credentials" section with:

```markdown
## Development credentials

Authentication uses a server-side session cookie. The dev workflow is
a one-liner against the same CLI a production operator would run:

```sh
just bootstrap-dev
```

This idempotently creates a `Development` tenant and an `admin` user
with password `admin`, then prints the new tenant's UUID for reference.
Production deployments run the equivalent commands directly in an init
container — there is no environment-conditional code in the server.

The CLI is the only bootstrap path; for additional users / tenants:

```sh
novamoc tenant create --display-name "Acme Corp"
novamoc user create alice
novamoc user add-to-tenant alice <tenant-uuid>
```

Browser SPA: navigate to `/login`. The auth cookie is HttpOnly and
SameSite=Lax; the SPA does not handle the token directly.

Scripts / curl:

```sh
curl -c cookies.txt -X POST http://localhost:8000/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin"}'
curl -b cookies.txt http://localhost:8000/auth/me
curl -b cookies.txt http://localhost:8000/schema
```

The OpenAPI doc at `/openapi` is exempt from authentication; everything
else returns 401 ``tenant_not_resolved`` without a valid session.
```

- [ ] **Step 2: Final verification matrix**

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
just ratchet
cd src/js/web && npm run check
```

Expected: all green; ratchet baselines unchanged or only decreasing; svelte-check clean.

- [ ] **Step 3: Confirm the live server runs cleanly**

```bash
just bootstrap-dev
uv run litestar --app novamoc.asgi:create_app run --port 8001 &
sleep 2
curl -i -c /tmp/c.txt -X POST http://localhost:8001/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin"}'
curl -i -b /tmp/c.txt http://localhost:8001/auth/me
curl -i http://localhost:8001/schema  # should 401
curl -i -b /tmp/c.txt http://localhost:8001/schema  # should 200
kill %1
```

Expected: 204 on login (with Set-Cookie), 200 on me, 401 on unauthenticated GET /schema, 200 on authenticated GET /schema.

- [ ] **Step 4: Close issue #19 via the commit**

```bash
git add README.md
git commit -m "docs(readme): document the v2 auth flow

Closes #19."
```

- [ ] **Step 5: Push and open the PR**

```bash
git push
gh pr create --title "M5 Authentication & tenant registry" --body "$(cat <<'EOF'
## Summary

Implements ADR-020. Replaces the v1 hardcoded bearer token in
`domain/accounts/_resolver.py` with real `tenants` / `users` /
`user_tenant_memberships` / `sessions` tables, argon2id password
hashing, server-side session cookies via advanced-alchemy,
`POST /auth/login` + `POST /auth/logout` + `GET /auth/me`,
operator CLI commands, an idempotent dev-mode default-admin seeder,
and a minimal Svelte login page.

ADR-017's dispatch contract is preserved: handlers still see
`auth: RequestAuth`, the storage-layer listeners are untouched,
and the 401 wire shape is byte-identical to v1.

Closes #19.

## Test plan

- [ ] `uv run pytest` — full suite green
- [ ] `uv run ruff check src tests` — clean
- [ ] `uv run ty check` — clean
- [ ] `just ratchet` — counts unchanged or decreasing
- [ ] `cd src/js/web && npm run check` — clean
- [ ] Manual: `just bootstrap-dev` creates the dev admin idempotently
- [ ] Manual: login flow in browser at `/login`
- [ ] Manual: curl flow as documented in `README.md`
- [ ] Manual: `novamoc tenant create` / `novamoc user create` / `novamoc user add-to-tenant` (including the N:1 rejection on a second tenant)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

- *ADR-020* — Task 1.
- *`tenants` table + UUID type migration + `TenantService`* — Task 2.
- *`users` table with hashed passwords + `UserService` with case-folded usernames* — Task 3.
- *`user_tenant_memberships` table + service + N:1 write-time invariant* — Task 4.
- *`PasswordHasher` (argon2id, settings-driven cost)* — Task 5.
- *`AuthSettings` (no dev-seed), `LoginFailedError`, `UserAlreadyHasTenantError` + problem-details mappers* — Task 6.
- *`sessions` table via advanced-alchemy backend* — Task 7.
- *`Principal` struct (`.id`, not `.user_id`) + `LoginRequest` / `MeResponse` payloads* — Task 8.
- *Task 9: removed; bootstrap is CLI-driven via `just bootstrap-dev` (Task 15) which calls the same CLI an operator runs in production.*
- *`login` / `logout` / `me` handlers + `AuthController`* — Task 10.
- *Resolver rewrite, async middleware, session-middleware mount, problem-details map updates* — Task 11. **No seed hook.**
- *Wire e2e coverage of the three new endpoints + `unauth_client` fixture* — Task 12.
- *Operator CLI for tenant/user/auth management + N:1 CLI rejection test* — Task 13.
- *Svelte login page + layout auth probe* — Task 14.
- *`just bootstrap-dev` recipe + README + final verification + close #19* — Task 15.

No spec requirement is uncovered.

**File-count exceptions:** Task 2 (12 files) and Task 11 (10 files) are each flagged inline. Task 2 is the tenant-identity type migration (one conceptual seam touching every `tenant_id` column + the ContextVar + RequestAuth + scenarios). Task 11 is the v1-bearer → v2-session swap (resolver + middleware + asgi + conftest fixture). Neither splits cleanly without leaving the working tree red between tasks. The plan accepts the heuristic violations with rationale recorded inline.

**Placeholder scan:** No "TBD", no "implement later", no "add appropriate error handling". Where a concrete API call shape depends on advanced-alchemy or Litestar specifics that may shift between releases (e.g. `SQLAlchemyAsyncSessionBackend`'s exact import path in Task 7, `connection.app.plugins.get(...)` shape in Task 11's middleware), the plan calls out the existing reference site in the repo to match.

**Type consistency:** `Principal(id: str, username: str)` consistent across Tasks 8, 10, 11. `RequestAuth(tenant_id: uuid.UUID)` consistent across Tasks 2, 10, 11 (the type migration in Task 2 is the source of truth). `resolve_principal_from_session(session_payload, users, memberships) -> (Principal, RequestAuth)` consistent across Tasks 11 and the e2e tests in Task 12.

**Layering check:** Task 7's `Session` model is the one place where `db/models/` may need to touch a `litestar`-flavoured import (the advanced-alchemy session-backend mixin). The plan calls out two acceptable resolutions; pick at implementation time, document the chosen one in CLAUDE.md's "Critical layering rule" if needed.

**Anti-enumeration test:** Task 12 includes `test_wrong_password_and_unknown_user_indistinguishable` to confirm the spec's anti-enumeration guarantee. This is the test that pins the "don't leak which credential failed" property.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-14-authentication-and-tenant-registry.md`. Ready for execution.
