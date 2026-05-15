# Authentication & Tenant Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the design at `docs/superpowers/specs/2026-05-14-authentication-and-tenant-registry-design.md` — the v2 credential machinery ADR-017 deferred. Real `tenants` / `users` / `user_tenant_memberships` / `sessions` tables, argon2id password hashing, server-side session cookies via advanced-alchemy, `POST /auth/login` + `POST /auth/logout` + `GET /auth/me`, a dev-mode seeder that idempotently creates `admin`/`admin`, and a CLI for the production operator path. Closes issue #19.

**Architecture:** The resolver-as-swap-point structure from ADR-017 is preserved. `domain/accounts/_resolver.py` is rewritten from "header → constant match → tenant slug" into "session → user + active tenant lookup → `(Principal, RequestAuth)`". `AuthenticationMiddleware.authenticate_request` becomes async-with-DB-access; `TenantContextMiddleware` and the three storage-layer listeners are untouched. The new auth-layer tables live under `db/models/_auth/` and are NOT tenant-scoped — they short-circuit the listener's column-presence heuristic naturally. `SQLAlchemyAsyncSessionBackend` from advanced-alchemy stores sessions in the same DB.

**Tech Stack:** Python 3.14, Litestar 2.21.1, msgspec, advanced-alchemy + SQLAlchemy 2 (async), aiosqlite, argon2-cffi, Click (CLI), Svelte 5 + Vite (login page), pytest (asyncio auto mode), uv, ruff, ty.

**Milestone:** Proposed as **M5: Authentication & tenant registry** (numbering follows the M1–M4 convention in existing issues). Blocks M2 (`GET /events?since` for catch-up) and M3 (WS-transport with per-tenant subscriber registry) in the sense that both presume a real tenant identity. Does **not** block any in-flight M1 work.

---

## File map

**Created:**
- `docs/adr/020-authentication-and-tenant-registry.md` — the milestone ADR.
- `src/py/novamoc/db/models/_auth/__init__.py`
- `src/py/novamoc/db/models/_auth/_tenant.py` — `Tenant` model.
- `src/py/novamoc/db/models/_auth/_user.py` — `User` model.
- `src/py/novamoc/db/models/_auth/_membership.py` — `UserTenantMembership` model.
- `src/py/novamoc/db/models/_auth/_session.py` — `Session` model via advanced-alchemy's mixin.
- `src/py/novamoc/domain/accounts/_principal.py` — `Principal` frozen `msgspec.Struct`.
- `src/py/novamoc/domain/accounts/_password.py` — `PasswordHasher` accessor.
- `src/py/novamoc/domain/accounts/_services.py` — `TenantService`, `UserService`, `UserTenantMembershipService`.
- `src/py/novamoc/domain/accounts/_payloads.py` — `LoginRequest`, `MeResponse`, `MePrincipal`, `MeTenant`.
- `src/py/novamoc/domain/accounts/_handlers.py` — `login`, `logout`, `me` handler functions.
- `src/py/novamoc/domain/accounts/_seed.py` — `seed_default_admin`.
- `src/py/novamoc/domain/accounts/controllers/__init__.py`, `controllers/_auth.py` — `AuthController`.
- `src/py/novamoc/cli.py` — Click CLI entry point + sub-commands.
- `src/js/web/src/routes/login/+page.svelte` — the SPA login page.
- `tests/accounts/test_password.py`, `test_seed.py`, `test_resolver_session.py`, `test_login_e2e.py`, `test_logout_e2e.py`, `test_me_e2e.py`, `test_cli.py`.

**Modified:**
- `src/py/novamoc/asgi.py` — session middleware, `AuthController`, new problem-details mappers, dev-seed hook, hasher on `app.state`.
- `src/py/novamoc/config.py` — `AuthSettings` field on `Settings`.
- `src/py/novamoc/api/_problem_details.py` — add `LOGIN_FAILED` and `MULTIPLE_MEMBERSHIPS_UNSUPPORTED`.
- `src/py/novamoc/domain/_errors.py` — register the two new error codes on `ErrorCode`.
- `src/py/novamoc/domain/accounts/_resolver.py` — full rewrite.
- `src/py/novamoc/domain/accounts/_middleware.py` — async authenticate_request that reads session + DB.
- `src/py/novamoc/domain/accounts/_errors.py` — `LoginFailedError`, `MultipleMembershipsUnsupportedError`.
- `src/py/novamoc/domain/accounts/__init__.py` — re-exports.
- `src/py/novamoc/db/_listeners.py` — small allow-list pin (defensive).
- `src/py/novamoc/db/models/__init__.py` — import the new `_auth` sub-package so its tables register on the shared metadata.
- `tests/conftest.py` — drop the bearer header; add `dev_admin`, `authenticated_client`, `unauth_client`; tweak `tenant` fixture to seed a real `tenants` row.
- `pyproject.toml` — add `argon2-cffi` and `click` dependencies; declare the `novamoc` CLI entry point under `[project.scripts]`.
- `README.md` — document the new login flow.

**Deleted:**
- `_TENANT_T1_DEV_TOKEN` constant and the bearer-matching code in `_resolver.py`.
- Bearer-header default in `tests/conftest.py::client`.

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
- **Decision outcome:** session cookie via advanced-alchemy's `SQLAlchemyAsyncSessionBackend`. The principal/scope split inherits from ADR-017. The `tenants.id` PK is a slug (not UUID) so existing `tenant_id: str` columns and scenario fixtures remain valid. The membership table is N-to-N from day one with a v1 invariant of exactly-one-membership enforced at login. Dev seeding is gated by `NOVAMOC_DEV_SEED_DEFAULT_ADMIN`.
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

## Task 2: Add `argon2-cffi` + `click`; wire `Tenant` model and service

**Files:**
- Modify: `pyproject.toml`
- Create: `src/py/novamoc/db/models/_auth/__init__.py`
- Create: `src/py/novamoc/db/models/_auth/_tenant.py`
- Modify: `src/py/novamoc/db/models/__init__.py`
- Create: `src/py/novamoc/domain/accounts/_services.py`
- Create: `tests/accounts/test_tenant_model.py`

Tenants land first — they're the registry issue #19 actually tracks, and all the other auth tables FK to `tenants.id`. The dependency adds happen here so subsequent tasks can use them.

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml`. Append to `[project.dependencies]`:

```toml
"argon2-cffi>=23.1.0",
"click>=8.1.7",
```

Run `uv sync` to update the lock file.

- [ ] **Step 2: Write the failing test**

Create `tests/accounts/test_tenant_model.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_tenant


async def test_tenant_row_inserts_and_reads(session) -> None:
    from novamoc.db.models._auth import Tenant

    session.add(Tenant(id="dev", display_name="Development"))
    await session.flush()
    result = await session.get(Tenant, "dev")
    assert result is not None
    assert result.display_name == "Development"
    assert result.disabled_at is None


async def test_tenant_id_must_be_slug_shaped(session) -> None:
    """Service-layer validator rejects non-slug ids."""
    from novamoc.domain.accounts._services import TenantService

    service = TenantService(session=session)
    with pytest.raises(ValueError, match="slug"):
        await service.create({"id": "Invalid Slug!", "display_name": "x"})
```

Note the `no_tenant` marker — the `tenants` table is not tenant-scoped, so the autouse `tenant` fixture's auto-injection would be a false signal. The marker is the documented opt-out per CLAUDE.md.

- [ ] **Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/accounts/test_tenant_model.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `Tenant`**

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

PK is a short human-readable slug, not a UUID, so existing ``tenant_id``
columns on synced tables (and the ``"t1"`` value baked into scenario
fixtures) remain valid by construction. Slug validation lives at the
service layer.
"""

from __future__ import annotations

from datetime import datetime

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(UUIDAuditBase):
    __tablename__ = "tenants"

    # Override the inherited UUID PK with a string slug.
    id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)
```

Update `src/py/novamoc/db/models/__init__.py` to import the sub-package so its tables register on the shared metadata:

```python
import novamoc.db.models._auth  # noqa: F401
```

- [ ] **Step 5: Implement `TenantService`**

Create `src/py/novamoc/domain/accounts/_services.py`:

```python
"""Advanced-alchemy services for the auth-layer tables.

Thin ``SQLAlchemyAsyncRepositoryService`` wrappers; the only business
rule is the tenant-id slug validator. Other validation (uniqueness,
foreign-key existence) is enforced at the database level.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncRepositoryService

from novamoc.db.models._auth import Tenant

if TYPE_CHECKING:
    from collections.abc import Mapping

_TENANT_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")


class TenantService(SQLAlchemyAsyncRepositoryService[Tenant]):
    class Repo(SQLAlchemyAsyncRepositoryService[Tenant].repository_type):
        model_type = Tenant

    repository_type = Repo

    async def create(self, data: Mapping[str, Any] | Tenant, **kwargs: Any) -> Tenant:
        if isinstance(data, Mapping):
            tenant_id = data.get("id")
            if not isinstance(tenant_id, str) or not _TENANT_SLUG_PATTERN.fullmatch(tenant_id):
                msg = f"tenant id must be a slug matching {_TENANT_SLUG_PATTERN.pattern}; got {tenant_id!r}"
                raise ValueError(msg)
        return await super().create(data=data, **kwargs)
```

(The exact `SQLAlchemyAsyncRepositoryService` boilerplate may need adjustment to match advanced-alchemy's current API; the existing services under `domain/schema/services/` are the reference shape.)

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/accounts/test_tenant_model.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Run the full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green. The new metadata import in `db/models/__init__.py` means the test in-memory engine now creates the `tenants` table — existing tests under `tests/` should be unaffected (no other code references `tenants` yet).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock \
        src/py/novamoc/db/models/_auth/ \
        src/py/novamoc/db/models/__init__.py \
        src/py/novamoc/domain/accounts/_services.py \
        tests/accounts/test_tenant_model.py
git commit -m "feat(accounts): Tenant model + service; slug-validated PK"
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

## Task 4: `UserTenantMembership` model + service

**Files:**
- Create: `src/py/novamoc/db/models/_auth/_membership.py`
- Modify: `src/py/novamoc/db/models/_auth/__init__.py`
- Modify: `src/py/novamoc/domain/accounts/_services.py` — add `UserTenantMembershipService`.
- Create: `tests/accounts/test_membership_model.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_membership_model.py`:

```python
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.no_tenant


async def test_membership_inserts_with_real_fks(session) -> None:
    from novamoc.db.models._auth import Tenant, User, UserTenantMembership

    tenant = Tenant(id="dev", display_name="Development")
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

    tenant = Tenant(id="dev", display_name="d")
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
            user_id=uuid.uuid4(), tenant_id="nonexistent"
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement `UserTenantMembership`**

Create `src/py/novamoc/db/models/_auth/_membership.py`:

```python
"""User ↔ Tenant membership (ADR-020).

Composite PK ``(user_id, tenant_id)`` doubles as the uniqueness
constraint. ``DefaultBase`` (not ``UUIDAuditBase``) because the
membership is a relation; its identity is the pair, not an opaque id.
v1 enforces one-membership-per-user at the login handler, NOT at the
schema level — the table allows N-to-N from day one so future "switch
active tenant" is a data change, not a schema change.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from advanced_alchemy.base import DefaultBase
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

if TYPE_CHECKING:
    pass


class UserTenantMembership(DefaultBase):
    __tablename__ = "user_tenant_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id"), primary_key=True
    )
```

Update `_auth/__init__.py` to re-export.

- [ ] **Step 4: Implement `UserTenantMembershipService`**

Append to `_services.py`:

```python
from novamoc.db.models._auth import UserTenantMembership


class UserTenantMembershipService(SQLAlchemyAsyncRepositoryService[UserTenantMembership]):
    class Repo(SQLAlchemyAsyncRepositoryService[UserTenantMembership].repository_type):
        model_type = UserTenantMembership

    repository_type = Repo

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserTenantMembership]:
        return await self.list(user_id=user_id)
```

- [ ] **Step 5: Run the tests + full suite + lint + type-check**

Expected: all green. Note: SQLite enforces FK constraints only when `PRAGMA foreign_keys=ON`; the third test (orphan rejection) confirms the test harness has FK enforcement on. If it doesn't, add a `PRAGMA foreign_keys=ON` to the test engine factory in `tests/conftest.py` — but this is a one-line addition and should already be the case under aiosqlite's defaults.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/db/models/_auth/ \
        src/py/novamoc/domain/accounts/_services.py \
        tests/accounts/test_membership_model.py
git commit -m "feat(accounts): UserTenantMembership model + service"
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

## Task 6: `AuthSettings`, `AuthError` codes, and problem-details mappers

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `src/py/novamoc/domain/_errors.py`
- Modify: `src/py/novamoc/domain/accounts/_errors.py`
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `tests/api/test_problem_details.py`

The error codes + their wire-shape mappers land before the handlers so the handlers have somewhere to raise into.

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


def test_multiple_memberships_unsupported_renders_409() -> None:
    from novamoc.api._problem_details import schema_error_to_problem_details
    from novamoc.domain.accounts._errors import MultipleMembershipsUnsupportedError

    exc = MultipleMembershipsUnsupportedError()
    pd = schema_error_to_problem_details(exc)
    assert pd.status_code == 409
    assert pd.type_ == "urn:novamoc:problems:multiple_memberships_unsupported"
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the error codes**

Edit `src/py/novamoc/domain/_errors.py` (or wherever `ErrorCode` lives — see existing references for the canonical path). Append to `ErrorCode`:

```python
LOGIN_FAILED = "login_failed"
MULTIPLE_MEMBERSHIPS_UNSUPPORTED = "multiple_memberships_unsupported"
```

Edit `src/py/novamoc/domain/accounts/_errors.py`. Append:

```python
from novamoc.domain._errors import DomainError, ErrorCode


class LoginFailedError(DomainError):
    code = ErrorCode.LOGIN_FAILED
    status_code = 401
    default_message = "The provided credentials were not accepted."


class MultipleMembershipsUnsupportedError(DomainError):
    code = ErrorCode.MULTIPLE_MEMBERSHIPS_UNSUPPORTED
    status_code = 409
    default_message = (
        "This account is a member of multiple tenants; selecting an active "
        "tenant is not yet supported."
    )
```

(Exact `DomainError` API matches whatever the existing schema errors use; replicate the shape from `domain/schema/_errors.py`.)

Edit `src/py/novamoc/api/_problem_details.py`. Append rows to `_TITLES`:

```python
ErrorCode.LOGIN_FAILED: "Login failed",
ErrorCode.MULTIPLE_MEMBERSHIPS_UNSUPPORTED: "Multiple tenant memberships not supported",
```

And to `_STATUS_CODES`:

```python
ErrorCode.LOGIN_FAILED: 401,
ErrorCode.MULTIPLE_MEMBERSHIPS_UNSUPPORTED: 409,
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
    dev_seed_default_admin: bool = field(
        default_factory=_bool_env("NOVAMOC_DEV_SEED_DEFAULT_ADMIN", False)
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

- [ ] **Step 5: Run the tests + full suite + lint + type-check**

```bash
uv run pytest
uv run ruff check src tests
uv run ty check
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/config.py \
        src/py/novamoc/domain/_errors.py \
        src/py/novamoc/domain/accounts/_errors.py \
        src/py/novamoc/api/_problem_details.py \
        tests/api/test_problem_details.py
git commit -m "feat(accounts): AuthSettings + LoginFailedError + MultipleMembershipsUnsupportedError"
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

    p = Principal(user_id="abc", username="alice")
    assert p.user_id == "abc"
    assert p.username == "alice"


def test_principal_is_frozen() -> None:
    from novamoc.domain.accounts._principal import Principal

    p = Principal(user_id="abc", username="alice")
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
    user_id: str
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

## Task 9: `seed_default_admin` + tests

**Files:**
- Create: `src/py/novamoc/domain/accounts/_seed.py`
- Create: `tests/accounts/test_seed.py`

Idempotent dev seeder. Idempotent so test fixtures can call it freely; gated upstream by the `dev_seed_default_admin` setting (wired in Task 11).

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_seed.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_tenant


async def test_seed_creates_tenant_user_membership(session, settings) -> None:
    from novamoc.db.models._auth import Tenant, User, UserTenantMembership
    from novamoc.domain.accounts._seed import seed_default_admin

    await seed_default_admin(settings=settings, session=session)

    tenant = await session.get(Tenant, "dev")
    assert tenant is not None and tenant.display_name == "Development"

    from novamoc.domain.accounts._services import UserService
    user = await UserService(session=session).get_by_username("admin")
    assert user is not None

    membership = await session.get(UserTenantMembership, (user.id, "dev"))
    assert membership is not None


async def test_seed_is_idempotent(session, settings) -> None:
    from novamoc.db.models._auth import User
    from novamoc.domain.accounts._seed import seed_default_admin
    from novamoc.domain.accounts._services import UserService
    from sqlalchemy import select, func

    await seed_default_admin(settings=settings, session=session)
    await seed_default_admin(settings=settings, session=session)

    count = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    assert count == 1


async def test_seed_does_not_clobber_existing_admin(session, settings) -> None:
    from novamoc.domain.accounts._seed import seed_default_admin
    from novamoc.domain.accounts._services import UserService

    users = UserService(session=session)
    existing = await users.create(
        {"username": "admin", "password_hash": "preserved-hash"}
    )
    await seed_default_admin(settings=settings, session=session)
    refreshed = await users.get_by_username("admin")
    assert refreshed.password_hash == "preserved-hash"
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement `seed_default_admin`**

Create `src/py/novamoc/domain/accounts/_seed.py`:

```python
"""Dev-mode default-admin seeder.

Idempotent: skips when the ``admin`` user already exists. Production
deployments leave ``NOVAMOC_DEV_SEED_DEFAULT_ADMIN`` off and this
function never runs. The dev path logs a loud warning on first use.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.config import Settings

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = "dev"
_DEFAULT_TENANT_DISPLAY_NAME = "Development"
_DEFAULT_USERNAME = "admin"
_DEFAULT_PASSWORD = "admin"  # noqa: S105 — dev seed only, gated by setting


async def seed_default_admin(settings: Settings, session: AsyncSession) -> None:
    """Idempotently create the dev tenant + admin user + membership."""
    tenants = TenantService(session=session)
    users = UserService(session=session)
    memberships = UserTenantMembershipService(session=session)

    if await users.get_by_username(_DEFAULT_USERNAME) is not None:
        return  # already seeded; do nothing

    _LOGGER.warning(
        "Seeding default admin user '%s' with the documented dev password. "
        "Set NOVAMOC_DEV_SEED_DEFAULT_ADMIN=false in any non-dev deployment.",
        _DEFAULT_USERNAME,
    )

    if await tenants.get_one_or_none(id=_DEFAULT_TENANT_ID) is None:
        await tenants.create(
            {"id": _DEFAULT_TENANT_ID, "display_name": _DEFAULT_TENANT_DISPLAY_NAME}
        )

    hasher = PasswordHasher(
        time_cost=settings.auth.argon2_time_cost,
        memory_cost_kib=settings.auth.argon2_memory_cost_kib,
        parallelism=settings.auth.argon2_parallelism,
    )
    user = await users.create(
        {"username": _DEFAULT_USERNAME, "password_hash": hasher.hash(_DEFAULT_PASSWORD)}
    )

    await memberships.create(
        {"user_id": user.id, "tenant_id": _DEFAULT_TENANT_ID}
    )
```

- [ ] **Step 4: Run the tests + full suite + lint + type-check**

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/domain/accounts/_seed.py tests/accounts/test_seed.py
git commit -m "feat(accounts): idempotent seed_default_admin gated by AuthSettings"
```

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
from novamoc.domain.accounts._errors import (
    LoginFailedError,
    MultipleMembershipsUnsupportedError,
)
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

    user_memberships = await memberships.list_for_user(user.id)
    if len(user_memberships) == 0:
        raise LoginFailedError
    if len(user_memberships) > 1:
        raise MultipleMembershipsUnsupportedError

    active_tenant_id = user_memberships[0].tenant_id

    # Rehash on cost change — free upgrade for the active user.
    if password_hasher.check_needs_rehash(user.password_hash):
        await users.update(
            {"password_hash": password_hasher.hash(data.password)},
            item_id=user.id,
        )

    request.set_session({"user_id": str(user.id), "active_tenant_id": active_tenant_id})


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
        user=MePrincipal(id=principal.user_id, username=principal.username),
        tenant=MeTenant(id=tenant.id, display_name=tenant.display_name),
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


async def test_resolve_principal_returns_user_and_auth(session, settings) -> None:
    from novamoc.domain.accounts._principal import Principal
    from novamoc.domain.accounts._auth import RequestAuth
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._seed import seed_default_admin
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    await seed_default_admin(settings=settings, session=session)
    user = await UserService(session=session).get_by_username("admin")

    principal, auth = await resolve_principal_from_session(
        session_payload={"user_id": str(user.id), "active_tenant_id": "dev"},
        users=UserService(session=session),
        memberships=UserTenantMembershipService(session=session),
    )

    assert isinstance(principal, Principal)
    assert principal.username == "admin"
    assert auth == RequestAuth(tenant_id="dev")


async def test_missing_session_keys_raises(session) -> None:
    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    for payload in ({}, {"user_id": "x"}, {"active_tenant_id": "dev"}):
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
            session_payload={"user_id": str(uuid.uuid4()), "active_tenant_id": "dev"},
            users=UserService(session=session),
            memberships=UserTenantMembershipService(session=session),
        )


async def test_disabled_user_raises(session, settings) -> None:
    from datetime import UTC, datetime

    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._seed import seed_default_admin
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    await seed_default_admin(settings=settings, session=session)
    users = UserService(session=session)
    user = await users.get_by_username("admin")
    await users.update({"disabled_at": datetime.now(UTC)}, item_id=user.id)

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            session_payload={"user_id": str(user.id), "active_tenant_id": "dev"},
            users=users,
            memberships=UserTenantMembershipService(session=session),
        )


async def test_missing_membership_raises(session, settings) -> None:
    from novamoc.domain.accounts._errors import TenantResolutionError
    from novamoc.domain.accounts._resolver import resolve_principal_from_session
    from novamoc.domain.accounts._seed import seed_default_admin
    from novamoc.domain.accounts._services import (
        UserService,
        UserTenantMembershipService,
    )

    await seed_default_admin(settings=settings, session=session)
    user = await UserService(session=session).get_by_username("admin")

    with pytest.raises(TenantResolutionError):
        await resolve_principal_from_session(
            session_payload={
                "user_id": str(user.id),
                "active_tenant_id": "some-other-tenant",
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
        Principal(user_id=str(user.id), username=user.username),
        RequestAuth(tenant_id=active_tenant_id),
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
    MultipleMembershipsUnsupportedError,
    TenantResolutionError,
)
from novamoc.domain.accounts._middleware import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
)
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._principal import Principal
from novamoc.domain.accounts._seed import seed_default_admin
from novamoc.domain.accounts.controllers import AuthController

__all__ = (
    "AuthController",
    "AuthenticationMiddleware",
    "LoginFailedError",
    "MultipleMembershipsUnsupportedError",
    "PasswordHasher",
    "Principal",
    "RequestAuth",
    "TenantContextMiddleware",
    "TenantResolutionError",
    "seed_default_admin",
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
    make_multiple_memberships_error_converter,
    # ... existing imports
)
from novamoc.domain.accounts import (
    AuthController,
    AuthenticationMiddleware,
    LoginFailedError,
    MultipleMembershipsUnsupportedError,
    PasswordHasher,
    TenantContextMiddleware,
    TenantResolutionError,
    seed_default_admin,
)
```

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
    MultipleMembershipsUnsupportedError: make_multiple_memberships_error_converter(base_url),
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

6. Stash the password hasher on `app.state` and gate the dev seed:

```python
from litestar.events import listener
from litestar.types import ASGIApp

password_hasher = PasswordHasher(
    time_cost=s.auth.argon2_time_cost,
    memory_cost_kib=s.auth.argon2_memory_cost_kib,
    parallelism=s.auth.argon2_parallelism,
)

# ... in Litestar(...):
on_startup=[_build_startup_hook(s, alchemy_config, password_hasher)],
state=State({"settings": s, "password_hasher": password_hasher}),
```

with a small startup hook:

```python
def _build_startup_hook(s, alchemy_config, password_hasher):
    async def _hook(app):
        if not s.auth.dev_seed_default_admin:
            return
        async with alchemy_config.get_session() as db_session:
            await seed_default_admin(settings=s, session=db_session)
            await db_session.commit()
    return _hook
```

7. Add the problem-details factories in `api/_problem_details.py` if they don't already follow from `make_domain_error_converter`. If your existing converter dispatches on `ErrorCode`, no new factory is needed — `LoginFailedError` and `MultipleMembershipsUnsupportedError` inherit from `DomainError` and just need the `_TITLES`/`_STATUS_CODES` rows from Task 6.

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

- [ ] **Step 8: Preview-wire `conftest.py`**

This is a partial conftest update — just enough to get `tests/accounts/test_resolver_session.py` passing. Full migration is Task 12.

In `tests/conftest.py`, drop the `_TENANT_T1_DEV_TOKEN` import — it no longer exists. Replace the `client` fixture body with a `pytest.skip(...)` placeholder for now (Task 12 rewrites it properly). The handler-level tests and the new `test_resolver_session.py` tests do not use `client`, so they pass; the schema/events e2e tests will be temporarily skipped at this commit boundary.

Wait — temporarily skipping the schema/events e2e tests breaks the "working tree green at every commit boundary" rule. Two options:

A. Land the conftest migration **in this same commit** (mostly the rewrite, full coverage). Pushes this task's file count higher.
B. Keep the existing conftest's `client` fixture but make it call `POST /auth/login` once at construction. Requires the seed hook to fire; needs the test app to have `dev_seed_default_admin=True`.

Option B is the right call:

```python
# In conftest's `settings` fixture, set:
auth=AuthSettings(dev_seed_default_admin=True)

# In the `client` fixture:
async with AsyncTestClient(app) as c:
    resp = await c.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 204, resp.text
    yield c
```

With this in place every existing schema/events e2e test logs in once at fixture setup and reuses the session cookie for subsequent requests. Migrate the conftest in this commit; Task 12 builds on top with the `unauth_client` and `authenticated_client` fixtures.

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


async def test_user_with_two_memberships_returns_409(unauth_client, app, session) -> None:
    from novamoc.db.models._auth import Tenant, UserTenantMembership
    from novamoc.domain.accounts._services import (
        TenantService,
        UserService,
        UserTenantMembershipService,
    )

    # The seeded `admin` user has one membership to `dev`. Add a second.
    tenants = TenantService(session=session)
    memberships = UserTenantMembershipService(session=session)
    users = UserService(session=session)
    await tenants.create({"id": "second", "display_name": "Second"})
    admin = await users.get_by_username("admin")
    await memberships.create({"user_id": admin.id, "tenant_id": "second"})
    await session.commit()

    resp = await unauth_client.post(
        "/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "urn:novamoc:problems:multiple_memberships_unsupported"
```

(The second-membership test depends on the test app sharing a database with the test's `session` fixture — verified by the `StaticPool` config in `tests/conftest.py::settings`. The `app` fixture parameter on that test is unused but listed so the fixture is constructed; the conftest's app fixture seeds `admin` at startup.)

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
    result = runner.invoke(main, ["tenant", "create", "acme", "--display-name", "Acme"])
    assert result.exit_code == 0, result.output


def test_tenant_create_duplicate_errors(settings) -> None:
    from novamoc.cli import main

    runner = CliRunner()
    runner.invoke(main, ["tenant", "create", "acme", "--display-name", "Acme"])
    result = runner.invoke(main, ["tenant", "create", "acme", "--display-name", "Acme"])
    assert result.exit_code != 0
    assert "already exists" in result.output.lower() or "exists" in result.output.lower()


def test_user_create_then_add_to_tenant(settings) -> None:
    from novamoc.cli import main

    runner = CliRunner()
    runner.invoke(main, ["tenant", "create", "acme", "--display-name", "Acme"])
    r1 = runner.invoke(main, ["user", "create", "bob", "--password", "bob-secret"])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(main, ["user", "add-to-tenant", "bob", "acme"])
    assert r2.exit_code == 0, r2.output


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
@click.argument("slug")
@click.option("--display-name", required=True)
def tenant_create(slug: str, display_name: str) -> None:
    """Create a tenant with the given slug."""

    async def run() -> None:
        _settings, config = await _session_context()
        async with config.get_session() as session:
            try:
                await TenantService(session=session).create(
                    {"id": slug, "display_name": display_name}
                )
                await session.commit()
                click.echo(f"Created tenant '{slug}'.")
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
@click.argument("tenant_slug")
def user_add_to_tenant(username: str, tenant_slug: str) -> None:
    async def run() -> None:
        _settings, config = await _session_context()
        async with config.get_session() as session:
            users = UserService(session=session)
            target = await users.get_by_username(username)
            if target is None:
                click.echo(f"User '{username}' not found.", err=True)
                sys.exit(1)
            await UserTenantMembershipService(session=session).create(
                {"user_id": target.id, "tenant_id": tenant_slug}
            )
            await session.commit()
            click.echo(f"Added '{username}' to tenant '{tenant_slug}'.")

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
# Terminal 1 — backend with dev seed on:
NOVAMOC_DEV_SEED_DEFAULT_ADMIN=true uv run litestar --app novamoc.asgi:create_app run

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

## Task 15: Documentation + README + final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Replace the existing "Development credentials" section with:

```markdown
## Development credentials

Authentication uses a server-side session cookie. The dev server can
seed a default admin user at startup:

```sh
NOVAMOC_DEV_SEED_DEFAULT_ADMIN=true uv run litestar \
    --app novamoc.asgi:create_app run
```

This idempotently creates tenant `dev` and user `admin` (password
`admin`). Production deployments leave the env var off and create users
via the CLI:

```sh
novamoc tenant create acme --display-name "Acme Corp"
novamoc user create alice
novamoc user add-to-tenant alice acme
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
NOVAMOC_DEV_SEED_DEFAULT_ADMIN=true uv run litestar \
    --app novamoc.asgi:create_app run --port 8001 &
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
- [ ] Manual: login flow in browser at `/login`
- [ ] Manual: curl flow as documented in `README.md`
- [ ] Manual: `novamoc tenant create` / `novamoc user create` / `novamoc user add-to-tenant`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

- *ADR-020* — Task 1.
- *`tenants` table + `TenantService` with slug validator* — Task 2.
- *`users` table with hashed passwords + `UserService` with case-folded usernames* — Task 3.
- *`user_tenant_memberships` table + service* — Task 4.
- *`PasswordHasher` (argon2id, settings-driven cost)* — Task 5.
- *`AuthSettings`, `LoginFailedError`, `MultipleMembershipsUnsupportedError` + problem-details mappers* — Task 6.
- *`sessions` table via advanced-alchemy backend* — Task 7.
- *`Principal` struct + `LoginRequest` / `MeResponse` payloads* — Task 8.
- *Idempotent `seed_default_admin`* — Task 9.
- *`login` / `logout` / `me` handlers + `AuthController`* — Task 10.
- *Resolver rewrite, async middleware, session-middleware mount, problem-details map updates, dev seed hook* — Task 11.
- *Wire e2e coverage of the three new endpoints + `unauth_client` fixture* — Task 12.
- *Operator CLI for tenant/user/auth management* — Task 13.
- *Svelte login page + layout auth probe* — Task 14.
- *README + final verification + close #19* — Task 15.

No spec requirement is uncovered.

**File-count exceptions:** Task 11 (10 files) is flagged inline. The resolver/middleware rewrite + asgi wiring + conftest preview is one conceptual seam (the v1-bearer → v2-session swap) that cannot split cleanly without leaving the test suite red between tasks. The plan accepts the heuristic violation with the rationale recorded.

**Placeholder scan:** No "TBD", no "implement later", no "add appropriate error handling". Where a concrete API call shape depends on advanced-alchemy or Litestar specifics that may shift between releases (e.g. `SQLAlchemyAsyncSessionBackend`'s exact import path in Task 7, `connection.app.plugins.get(...)` shape in Task 11's middleware), the plan calls out the existing reference site in the repo to match.

**Type consistency:** `Principal(user_id: str, username: str)` consistent across Tasks 8, 10, 11. `RequestAuth(tenant_id: str)` unchanged from ADR-017. `resolve_principal_from_session(session_payload, users, memberships) -> (Principal, RequestAuth)` consistent across Tasks 11 and the e2e tests in Task 12.

**Layering check:** Task 7's `Session` model is the one place where `db/models/` may need to touch a `litestar`-flavoured import (the advanced-alchemy session-backend mixin). The plan calls out two acceptable resolutions; pick at implementation time, document the chosen one in CLAUDE.md's "Critical layering rule" if needed.

**Anti-enumeration test:** Task 12 includes `test_wrong_password_and_unknown_user_indistinguishable` to confirm the spec's anti-enumeration guarantee. This is the test that pins the "don't leak which credential failed" property.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-14-authentication-and-tenant-registry.md`. Ready for execution.
