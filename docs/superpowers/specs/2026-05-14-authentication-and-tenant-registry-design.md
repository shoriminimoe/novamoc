# Authentication & Tenant Registry Design

## Status

Draft

## Purpose & scope

Replace the v1 hardcoded bearer token (single constant in `domain/accounts/_resolver.py`, matched against `Authorization: Bearer <token>` and yielding tenant `"t1"`) with the real machinery that ADR-017 deferred: persistent **tenants** and **users** tables, a per-user **password** credential, a **session** backed by an HttpOnly cookie, and login / logout / "who am I" endpoints. The work closes [issue #19](https://github.com/shoriminimoe/novamoc/issues/19) and lands the `User` principal that `RequestAuth.user` left as `None`.

The dispatch contract ADR-017 fixed (handlers see `auth: RequestAuth`; storage-layer listeners read `current_tenant_id`; the OpenAPI doc is exempt from the credential check; failures render as `401 application/problem+json`) is preserved verbatim. The credential-resolution module is the swap point — the rest of the surface stays put.

In scope:

- A real **tenants** table (the registry issue #19 tracks). Per-row PK is a slug-shaped string so the existing `tenant_id: str` columns and the `"t1"` scenario fixtures keep working.
- A **users** table with hashed passwords (argon2id via `argon2-cffi`).
- A **user_tenant_memberships** join table (N-to-N from day one; v1 enforces a one-membership-per-user invariant at the handler level so "switch active tenant" is a later data change, not a schema change).
- A **sessions** table backed by `advanced_alchemy.extensions.litestar.SQLAlchemyAsyncSessionBackend` (server-side, single-DB story, immediate revocation).
- **`POST /auth/login`**, **`POST /auth/logout`**, **`GET /auth/me`** — three minimal HTTP endpoints; everything else stays where it is.
- A rewrite of `domain/accounts/_resolver.py` from "match bearer constant" to "read session, load user, return `(Principal, RequestAuth)`". The middleware and `RequestAuth.tenant_id` consumer surface do not change.
- **Dev-mode seeding** gated by `NOVAMOC_DEV_SEED_DEFAULT_ADMIN=true`: on startup, idempotently create tenant `dev`, user `admin` with password `admin`, and one membership linking them. Default off. Production deployments leave it off.
- **CLI commands** for the production path: `novamoc tenant create <slug>`, `novamoc user create <username>`, `novamoc user set-password <username>`, `novamoc user add-to-tenant <username> <tenant>`. The dev seeder is a thin caller of these.
- A minimal Svelte 5 login page at `/login` (the SPA scaffolding from CLAUDE.md is currently empty — a single route is the right milestone-sized addition; full SPA shell is a separate milestone).
- Test fixture migration: the `client` fixture stops attaching a bearer header and instead starts an authenticated session against a seeded `admin` user.

Out of scope:

- **Authorization** (per-action permissions, roles, schema-edit gates). ADR-017 explicitly defers per-action permissions to Litestar `Guard`s landed later; this milestone preserves that boundary.
- **Multiple active tenants per user.** The membership table is N-to-N so future work is a data change; v1 handlers refuse to log in a user with >1 membership.
- **OAuth / OIDC / SSO.** Authlib is the path when this becomes wanted; this milestone keeps the resolver as a single swap point so adding it later is a new login route, not a structural change.
- **Password reset by email, registration, email verification, 2FA, rate-limiting of failed logins.** Each is a tracked followup (see "Recorded tech debt" below). Operator-managed via CLI is the v1 story.
- **API tokens for non-browser callers** (CLI scripts, curl). Cookie-only for v1; the dev workflow uses `curl -c cookies.txt` (documented in the README update). A future API-token model is a separate spec.

## HTTP contract changes

### Authentication is by session cookie

Three classes of endpoint after this milestone:

| Class | Examples | Behaviour without credentials |
|-------|----------|-------------------------------|
| **Public** | `GET /openapi`, `GET /problems/*`, `POST /auth/login` | No credential needed; reachable directly. |
| **Authenticated** | every other endpoint (`POST /schema`, `GET /schema`, `POST /events`, `POST /auth/logout`, `GET /auth/me`, future endpoints) | `401 tenant_not_resolved` with `application/problem+json`. |
| **OPTIONS** | any path | Bypass per Litestar's framework default (CORS preflight). |

The credential is a **`session_id`** cookie (HttpOnly, `SameSite=Lax`, `Path=/`, `Secure` when settings indicate HTTPS). Cookie name: `novamoc_session`. Encoded as advanced-alchemy's session backend formats it; the wire shape is opaque to clients.

### `POST /auth/login`

Request:

```http
POST /auth/login
Content-Type: application/json

{"username": "admin", "password": "admin"}
```

Success (204):

```http
HTTP/1.1 204 No Content
Set-Cookie: novamoc_session=...; HttpOnly; SameSite=Lax; Path=/
```

The endpoint returns 204 with no body so the response carries no PII; the SPA reads `GET /auth/me` separately to discover the principal. (Returning a JSON body of the principal here would invite clients to skip the `me` round-trip, but `me` is the canonical "who am I now" probe — including for after-cookie-restore scenarios — and we want one source of truth.)

Failure modes, all rendered as RFC 9457 problem-details:

| Status | `type` URI leaf | Trigger |
|--------|-----------------|---------|
| 400 | `invalid_payload_shape` | Body is missing `username` or `password`, or has extra fields (`forbid_unknown_fields=True`). |
| 401 | `login_failed` | Username does not exist, password mismatches, user is disabled, or user has zero tenant memberships. The four sub-cases share one wire response so an attacker probing for valid usernames cannot distinguish them (anti-enumeration). |
| 409 | `multiple_memberships_unsupported` | The user has more than one tenant membership. v1 cannot pick an active tenant on the user's behalf; tracked as a followup. The 409 specifies the constraint without leaking which tenants exist. |

`POST /auth/login` is in the middleware's `exclude` regex so an unauthenticated request can reach the handler. Otherwise the chicken-and-egg breaks.

### `POST /auth/logout`

Request:

```http
POST /auth/logout
Cookie: novamoc_session=...
```

Success (204):

```http
HTTP/1.1 204 No Content
Set-Cookie: novamoc_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax
```

The handler calls `request.clear_session()`; the session middleware deletes the backend row and emits the cookie-clearing `Set-Cookie`. An unauthenticated `POST /auth/logout` returns the same 401 as any other authenticated endpoint — logout is not "fire-and-forget"; if you don't have a session, there is nothing to log out from.

### `GET /auth/me`

Request:

```http
GET /auth/me
Cookie: novamoc_session=...
```

Success (200):

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "user": {"id": "01HXYZ...", "username": "admin"},
  "tenant": {"id": "dev", "display_name": "Development"}
}
```

The shape is deliberately minimal — `id` and `username` for the principal, `id` and `display_name` for the active tenant. Future fields (avatar, roles, permissions) extend the response without breaking SPA code that only reads what it needs.

### `POST /schema`, `GET /schema`, `POST /events`

No HTTP-contract change. They keep the existing routes, payload structs, and response shapes. The only difference is that the request must carry a `novamoc_session` cookie instead of an `Authorization: Bearer <token>` header. The 401 path stays the same wire shape; only its trigger changes from "missing/wrong bearer token" to "missing/expired session cookie."

### Errors removed

| Removed | Reason |
|---------|--------|
| `Authorization: Bearer <token>` as a wire format | The dev bearer constant retires. The header is silently ignored if present (no special-case rejection) so legacy clients fail cleanly on the missing session cookie. |

### OpenAPI bypass extends

The `AuthenticationMiddleware`'s `exclude` regex grows from `^/(openapi|problems)` to `^/(openapi|problems|auth/login)`. The session middleware itself runs for every request (no exclude needed — it's cheap and the session blob is empty for unauthenticated callers).

## Data model

### `tenants`

```python
class Tenant(UUIDAuditBase):
    __tablename__ = "tenants"

    # Override the inherited UUID PK: tenant ids are short human-readable
    # slugs (e.g. "t1", "dev", "acme"). The slug *is* the PK so every
    # existing tenant_id reference (TenantScopedMixin columns, scenario
    # fixtures, ContextVar value) remains valid by construction.
    id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)
```

Constraint: `id ~ '^[a-z][a-z0-9_-]{0,30}$'` enforced at the service layer (a CHECK constraint is possible but advanced-alchemy services are the canonical write path; doubling up adds noise).

`tenants` is **not** tenant-scoped — it has no `tenant_id` column because rows in it *are* the tenants. The three tenant-scoping listeners short-circuit naturally (`tenant_id` column absent → no auto-injection, no fail-closed check).

`UUIDAuditBase` is overridden for the PK only; the `created_at` / `updated_at` columns it provides land unchanged.

`disabled_at` instead of a boolean `active` flag: timestamp is strictly more information at zero extra cost and matches what schema entities will eventually want when soft-disable lands there too. Login refuses users whose active tenant has `disabled_at IS NOT NULL`.

### `users`

```python
class User(UUIDAuditBase):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)
```

Like `tenants`, `users` is **not** tenant-scoped — a user account is a global identity that can be linked to one (or eventually many) tenants via `user_tenant_memberships`.

`username` is the human-supplied login identifier; case-folded to `NFKC` + lowercase at write time so `Admin` and `admin` are the same row. `password_hash` carries the full argon2id encoded string (`$argon2id$v=19$m=...$t=...$p=...$<salt>$<hash>`); rotation of cost parameters is a `PasswordHasher.check_needs_rehash` + rehash on next successful login (free upgrade for active users; dormant accounts upgrade on their next login).

`UUIDAuditBase`'s `id` (UUIDv7) is the PK. UUIDv7 (not the slug we used for tenants) because usernames change (rename support), so the stable identity is the surrogate.

### `user_tenant_memberships`

```python
class UserTenantMembership(DefaultBase):
    __tablename__ = "user_tenant_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id"), primary_key=True
    )
```

Composite PK `(user_id, tenant_id)` doubles as the uniqueness constraint. `DefaultBase` (not `UUIDAuditBase`) because the membership is a relation, not an entity — its identity is the pair, not an opaque id. No audit columns: a membership is either there or it isn't.

v1 invariant — enforced at login, not at the schema level: a user with `count(memberships) != 1` cannot log in. The 409 `multiple_memberships_unsupported` failure exposes the limit; the zero-membership case is folded into the generic `login_failed` 401 (anti-enumeration).

### `sessions`

Provided by `advanced_alchemy.extensions.litestar.SQLAlchemyAsyncSessionBackend` — we register its mixin against our metadata; the columns (`id` UUIDv7, `session_id` str, `data` LargeBinary, `expires_at` datetime, `created_at` / `updated_at`) match its conventions. The session payload we write is small:

```python
{"user_id": "01HXYZ...", "active_tenant_id": "dev"}
```

That is the entire payload. Anything richer (cached display name, last access time, scopes) lives on the user/membership rows; the session is a pointer.

Session TTL: `NOVAMOC_AUTH_SESSION_TTL_SECONDS`, default `86400` (24 hours). Inactive sessions past `expires_at` are deleted by a scheduled task; v1 has no scheduler yet, so cleanup is opportunistic — the backend prunes on the next access of an expired row, and a `novamoc auth gc-sessions` CLI command exists for operators. Tracked as a followup.

### Migration / schema-version implications

The new tables (`tenants`, `users`, `user_tenant_memberships`, `sessions`) are **not** tenant-scoped synced tables — they are auth-layer infrastructure. They do not appear in `schema_change_log`, do not get tenant-scoping listener treatment, and their existence is invisible to the sync protocol. Adding them does not bump `schema_version` for any tenant. (`tenant_id`'s value space is now constrained by the FK from `user_tenant_memberships`, but the listener machinery's behaviour is unchanged.)

## Tenant & user resolution mechanism

### Updated `Principal` and `RequestAuth`

ADR-017's `RequestAuth(tenant_id: str)` shape is preserved verbatim — handlers reading `request.auth.tenant_id` keep working. The new principal lands on the `user` slot:

```python
# src/py/novamoc/domain/accounts/_principal.py
import msgspec

class Principal(msgspec.Struct, frozen=True):
    user_id: str  # str repr of the UUIDv7 (handlers don't need uuid semantics)
    username: str
```

`Principal` deliberately omits `password_hash`, `disabled_at`, and the user's tenant memberships — those live on the SQLAlchemy `User` row, not on a request-scoped object. The struct exists to be cheap, immutable, and free of ORM-session attachment.

Handlers that need the full `User` row (none today; tracked for when audit columns land on event_log entries) read it via DI; the `Principal` they get from `request.user` is enough for log lines and the `GET /auth/me` response.

### Updated `_resolver.py` (the swap point)

Today: read header, match constant, return `tenant_id`. After:

```python
# Sketch only — full implementation in the plan
async def resolve_principal(
    connection: ASGIConnection,
    users: UserService,
    memberships: UserTenantMembershipService,
) -> tuple[Principal, RequestAuth]:
    """Resolve (user, active tenant) from the request's session.

    Raises ``TenantResolutionError`` when the session is missing, expired,
    or the user/membership it points at no longer exists or is disabled.
    """
    session = connection.session  # populated by SessionMiddleware
    user_id = session.get("user_id")
    active_tenant_id = session.get("active_tenant_id")
    if user_id is None or active_tenant_id is None:
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

The function signature changes from pure (headers → tenant_id) to async + service-injected (the user/membership lookups are real DB reads). The middleware that calls it adapts accordingly.

### Updated `AuthenticationMiddleware`

`AbstractAuthenticationMiddleware.authenticate_request` is async and is given an `ASGIConnection` — both fit naturally. The middleware acquires the user/membership services from the request-scoped SQLAlchemy session that `SQLAlchemyPlugin` already provides:

```python
class AuthenticationMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        sqlalchemy_session = connection.app.dependencies["db_session"](connection)
        # ...obtain UserService, UserTenantMembershipService...
        principal, auth = await resolve_principal(connection, users, memberships)
        return AuthenticationResult(user=principal, auth=auth)
```

(The exact DI plumbing is settled in the plan; the shape is correct.)

`TenantContextMiddleware` is **unchanged** — it still reads `scope["auth"].tenant_id` and calls `use_tenant(...)`. The fact that the resolver is now async and DB-backed is invisible to it.

### Session middleware

A new entry in the app's `middleware=[...]` list, mounted **before** `AuthenticationMiddleware` so `connection.session` is populated by the time we read it:

```python
middleware=[
    session_config.middleware,             # ← new, populates connection.session
    DefineMiddleware(AuthenticationMiddleware, exclude=r"^/(openapi|problems|auth/login)"),
    TenantContextMiddleware(),
]
```

`session_config` is a `ServerSideSessionConfig` constructed from advanced-alchemy's session backend. The backend takes the same `SQLAlchemyAsyncConfig` already in use — sessions land in the same database.

The session middleware does not exclude `/auth/login` — login *writes* the session, so it needs the middleware machinery. Only the authentication middleware excludes login.

### Password hashing

`argon2-cffi`'s `PasswordHasher` with library defaults (m=64 MiB, t=3, p=4 as of the current release — OWASP-aligned). The hasher is constructed once at app init and stored on `app.state.password_hasher` so it can be DI-injected into the login handler and the CLI commands. Settings allow overriding cost parameters via env vars for tuning (`NOVAMOC_AUTH_ARGON2_TIME_COST`, `NOVAMOC_AUTH_ARGON2_MEMORY_COST_KIB`, `NOVAMOC_AUTH_ARGON2_PARALLELISM`).

`check_needs_rehash` is called after every successful verify; if it returns true, the login handler rehashes the supplied password and writes the new hash. This is the standard cost-rotation strategy.

## Code surface

**Created:**

- `src/py/novamoc/db/models/_auth/__init__.py` — package marker for the new auth-layer models. Sub-package keeps them visibly distinct from synced data models (which live under `models/data/`) and schema models (under `models/schema/`).
- `src/py/novamoc/db/models/_auth/_tenant.py` — `Tenant` model.
- `src/py/novamoc/db/models/_auth/_user.py` — `User` model.
- `src/py/novamoc/db/models/_auth/_membership.py` — `UserTenantMembership` model.
- `src/py/novamoc/db/models/_auth/_session.py` — `Session` model via advanced-alchemy's `SQLAlchemyAsyncSessionBackend` mixin.
- `src/py/novamoc/domain/accounts/_principal.py` — `Principal` frozen `msgspec.Struct`.
- `src/py/novamoc/domain/accounts/_password.py` — `PasswordHasher` accessor (thin wrapper that pulls the cached hasher off `app.state`; reads settings on first build).
- `src/py/novamoc/domain/accounts/_services.py` — `TenantService`, `UserService`, `UserTenantMembershipService` — advanced-alchemy `SQLAlchemyAsyncRepositoryService` wrappers. One file because each is ≤15 lines.
- `src/py/novamoc/domain/accounts/_payloads.py` — `LoginRequest`, `MeResponse`, `MePrincipal`, `MeTenant` msgspec Structs.
- `src/py/novamoc/domain/accounts/_handlers.py` — `login`, `logout`, `me` handlers. Single file (3 handlers, each ≤30 lines).
- `src/py/novamoc/domain/accounts/_errors.py` — gains `LoginFailedError`, `MultipleMembershipsUnsupportedError`. The existing `TenantResolutionError` stays as the umbrella for "session can't be resolved" (its 401 wire shape is reused).
- `src/py/novamoc/domain/accounts/controllers/__init__.py`, `controllers/_auth.py` — `AuthController` mounting `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- `src/py/novamoc/domain/accounts/_seed.py` — `seed_default_admin(settings, session)` async function. Idempotent: skips if the `admin` user already exists. Called from `create_app` only when `NOVAMOC_DEV_SEED_DEFAULT_ADMIN=true`.
- `src/py/novamoc/cli.py` — Click-based CLI (`novamoc tenant ...`, `novamoc user ...`, `novamoc auth gc-sessions`). The dev seeder calls into the same service code as the CLI so there's one canonical write path.
- `src/js/web/src/routes/login/+page.svelte` — the SPA's first non-scaffolding component. Minimal form, POSTs to `/auth/login`, redirects on success. Uses Svelte 5 runes per repo conventions.
- `tests/accounts/test_password.py`, `tests/accounts/test_seed.py`, `tests/accounts/test_login_e2e.py`, `tests/accounts/test_logout_e2e.py`, `tests/accounts/test_me_e2e.py`, `tests/accounts/test_resolver_session.py`, `tests/accounts/test_cli.py` — unit + e2e coverage for the new surface.
- `docs/adr/020-authentication-and-tenant-registry.md` — the ADR for this milestone. (ADR-019 is taken by the properties-mirrors-full-schema-state decision per `docs/adr/`'s current list.)

**Modified:**

- `src/py/novamoc/domain/accounts/_auth.py` — `RequestAuth` shape is unchanged; the file gets a docstring note that the v2 resolver now populates the principal too.
- `src/py/novamoc/domain/accounts/_resolver.py` — full rewrite: dev bearer constant deleted; new `resolve_principal(connection, users, memberships) -> (Principal, RequestAuth)` async function. This is the swap point ADR-017 designed for.
- `src/py/novamoc/domain/accounts/_middleware.py` — `AuthenticationMiddleware.authenticate_request` becomes async-with-DB-access; reads the request-scoped SQLAlchemy session, builds the two services, calls `resolve_principal`. `TenantContextMiddleware` is untouched.
- `src/py/novamoc/domain/accounts/__init__.py` — re-export `AuthController`, `Principal`, `seed_default_admin`; drop the (now-deleted) `_TENANT_T1_DEV_TOKEN` import path.
- `src/py/novamoc/asgi.py` — register `ServerSideSessionConfig.middleware` upstream of auth; register `AuthController` alongside `SchemaController` and `EventsController`; register `LoginFailedError` and `MultipleMembershipsUnsupportedError` in the problem-details map; call `seed_default_admin` from a `before_startup` hook when the setting is on; build the password hasher once and stash on `app.state.password_hasher`.
- `src/py/novamoc/config.py` — gains `AuthSettings` (slots dataclass) with `session_ttl_seconds`, `session_cookie_name`, `session_cookie_secure`, `dev_seed_default_admin`, plus the argon2 cost parameters; `Settings.auth` field.
- `src/py/novamoc/api/_problem_details.py` — add `LOGIN_FAILED` (401) and `MULTIPLE_MEMBERSHIPS_UNSUPPORTED` (409) to `_TITLES` / `_STATUS_CODES` / the domain-error converter's enum membership.
- `src/py/novamoc/domain/_errors.py` — register the two new error codes in `ErrorCode`.
- `src/py/novamoc/db/_listeners.py` — no changes to the listener logic, but a one-line addition to the "always-unscoped tables" allow-list (a private constant) so `tenants`, `users`, `user_tenant_memberships`, `sessions` are explicitly excluded from the column-presence heuristic. (The heuristic already does the right thing for tables without a `tenant_id` column, but pinning the intent in code prevents accidental future regressions.)
- `tests/conftest.py` — drop the `_TENANT_T1_DEV_TOKEN` import and the bearer-header default. Replace with: a session-wide `dev_admin` fixture that runs `seed_default_admin` against the per-test engine; an authenticated `client` fixture that calls `POST /auth/login` once at startup; and an `unauth_client` fixture for the rejection-path tests. The autouse `tenant` fixture keeps its current shape but now defaults to seeding a real `tenants` row with id `"t1"` so the storage-layer tests continue to pass under the FK constraint that `user_tenant_memberships` creates against `tenants.id`.
- `tests/schema/test_endpoint_e2e.py`, `tests/schema/test_read_endpoint_e2e.py`, `tests/events/test_endpoint_e2e.py`, `tests/events/test_endpoint_lifecycle_e2e.py` — no functional changes; the migrated `client` fixture means tests get an authenticated session by default. The 401 cases on these endpoints already exist (from the ADR-017 work); their wire shape doesn't change.
- `README.md` — replace the "Development credentials" section with the new flow (login at `/login`, or curl with `-c cookies.txt -X POST /auth/login`; admin / admin default; the env var that enables seeding).

**Deleted:**

- `_TENANT_T1_DEV_TOKEN` constant in `_resolver.py`.
- The bearer-header default on the `client` fixture in `tests/conftest.py`.
- The compatibility note in `_auth.py` about `user` being `None`.

## Testing

Repo conventions apply: real in-memory aiosqlite, no DB mocks, asyncio auto mode. New tests:

**`tests/accounts/test_password.py`** — unit tests against `_password.PasswordHasher`. Hash a password, verify the same password, verify a wrong password returns false, `check_needs_rehash` returns true when cost params change, `hash()` produces distinct outputs for the same input (salting).

**`tests/accounts/test_seed.py`** — unit tests for `seed_default_admin`. Fresh DB → creates tenant + user + membership; running twice is a no-op (idempotent); running with a pre-existing `admin` user with a different password leaves the existing user alone (no clobber).

**`tests/accounts/test_login_e2e.py`** — wire-level tests against the `app` fixture, against a seeded admin user:
- Valid credentials → 204, `Set-Cookie: novamoc_session=...` present, cookie is HttpOnly + SameSite=Lax.
- Wrong password → 401 `login_failed` (problem-details).
- Unknown username → 401 `login_failed` (same wire shape — anti-enumeration check; the test asserts the response body is byte-identical to the wrong-password case).
- Disabled user → 401 `login_failed`.
- User with 0 memberships → 401 `login_failed`.
- User with 2 memberships → 409 `multiple_memberships_unsupported`.
- Missing `username` or `password` field → 400 `invalid_payload_shape`.
- Extra field → 400 `invalid_payload_shape` (forbid_unknown_fields).

**`tests/accounts/test_logout_e2e.py`**:
- Authenticated session → 204, `Set-Cookie: novamoc_session=` with `Max-Age=0`.
- After logout the same cookie returns 401 on a follow-up request (session row deleted).
- Unauthenticated logout → 401 `tenant_not_resolved` (the umbrella 401 stays).

**`tests/accounts/test_me_e2e.py`**:
- Authenticated → 200 with `{"user": {"id": ..., "username": "admin"}, "tenant": {"id": "dev", "display_name": "Development"}}`.
- Unauthenticated → 401.
- After tenant `disabled_at` is set, subsequent requests fail authentication → 401.

**`tests/accounts/test_resolver_session.py`** — direct unit tests for `resolve_principal`:
- Missing session keys → raises `TenantResolutionError`.
- `user_id` pointing at a non-existent user → raises.
- Disabled user → raises.
- Membership missing → raises.
- Happy path → returns the expected `(Principal, RequestAuth)`.

**`tests/accounts/test_cli.py`** — exercises the CLI commands via Click's testing runner:
- `novamoc tenant create dev` creates a row; idempotent re-run errors with a clear message.
- `novamoc user create bob` prompts for a password (or accepts `--password` for tests).
- `novamoc user set-password bob` rehashes.
- `novamoc user add-to-tenant bob dev` creates the membership.
- `novamoc auth gc-sessions` deletes expired sessions.

**Existing tests** — mechanical edits via the fixture migration:
- All schema/events e2e tests pick up an authenticated session via the migrated `client` fixture; no per-test edits needed.
- The cross-tenant isolation test (`tests/schema/test_cross_tenant_isolation.py`) seeds two real `tenants` rows (`t-a`, `t-b`), two users, two memberships, and either logs in twice (one client per user) or — more efficient — calls `resolve_principal` directly to construct the per-tenant contexts without HTTP. Either is fine; the plan picks the simpler.

**Cross-cutting** — confirm the 401 wire shape on existing endpoints stays byte-identical to what e2e tests already assert. The trigger changes; the wire shape does not.

## ADR coordination

A new **ADR-020: Authentication and tenant registry** records the decisions here (ADR-019 is already taken by `properties-mirrors-full-schema-state`). ADR-020 follows the post-template MADR shape (YAML frontmatter, `Context and Problem Statement`, `Decision Drivers`, `Considered Options`, `Decision Outcome`, `Consequences`, `Confirmation`, `More Information`).

Substantive decisions ADR-020 records:

1. **Credential format.** Server-side session cookie via advanced-alchemy's `SQLAlchemyAsyncSessionBackend`. Considered options: stateless JWT in `Authorization`, JWT in cookie, session cookie. Choice: session cookie. Rationale: HttpOnly+SameSite cookie avoids XSS-readable token; same-origin SPA does not need stateless tokens; instant revocation; one DB, no Redis dependency.
2. **Principal/scope split inherits from ADR-017.** `Principal` lands on `request.user`; `RequestAuth(tenant_id)` shape preserved on `request.auth`. The struct extension story (future fields on Principal/RequestAuth) is unchanged.
3. **Tenant id is a slug (not a UUID).** Existing `tenant_id: str` columns and `"t1"` test fixtures stay valid; the `tenants` table's PK matches. Trade-off: tenants cannot be renamed in place; tenant rename is a data migration, not a column update. Accepted because (a) tenant ids are rarely renamed in practice and (b) immutable PKs prevent FK churn.
4. **N-to-N membership table with a v1 one-membership invariant.** Schema is forward-compatible; v1 behaviour is constrained to keep "switch active tenant" out of this milestone.
5. **Dev seeding gated by `NOVAMOC_DEV_SEED_DEFAULT_ADMIN`.** Default off. Idempotent. Loud warning on startup when on. The setting documents itself as dev-only; we do not attempt to detect "production" structurally (the operator's deployment config is the gate).
6. **No registration / no email reset in v1.** Operator-managed via CLI. Each deferred concern is enumerated as recorded tech debt.

ADR-020 does **not** supersede ADR-017 — ADR-017's structural decisions (resolver as the swap point, the principal/scope split, the 401 wire shape, the OpenAPI bypass) hold; ADR-020 fills in their v2 details. ADR-020's `More Information` cites ADR-017, ADR-014 (superseded by 017), ADR-008 (schema-as-data; where future authorization Guards will plug in), ADR-016 (problem-details), and issue #19 (closed by this milestone).

## Recorded tech debt

- **No registration endpoint, no public sign-up.** Users are created by CLI. Tracked: "Add operator-controlled invitation flow" (new issue when ADR-020 lands).
- **No password reset by email.** A user who forgets their password needs an operator to run `novamoc user set-password`. Tracked.
- **No 2FA / WebAuthn / passkeys.** OWASP recommends 2FA for any non-trivial auth surface; this is the next logical milestone after this one.
- **No rate-limiting on login.** A determined attacker can brute-force a weak password. OWASP-table-stakes deferred to keep this milestone bounded. Tracked.
- **No "switch active tenant" UX.** The membership table allows N-to-N from day one but the login handler refuses users with >1 membership (409). Tracked as M-next.
- **No session inactivity timeout, only absolute TTL.** A long-lived session does not refresh on activity; it just expires after the configured TTL. Tracked.
- **Opportunistic session cleanup.** No scheduled GC; the `novamoc auth gc-sessions` CLI command is the operator escape hatch. Tracked when the scheduler infra lands.
- **The dev `admin`/`admin` credential is in source.** Anyone with checkout access can read it; the same trust model ADR-017 articulated. The seeder logs a loud warning at startup. Production deployments leave the env var off.
- **No API tokens for CLI/automation.** Cookie-only for v1. A future "personal access token" model is its own spec.

## Notable non-changes

- **The dispatch contract ADR-017 fixed.** Handlers still take `auth: RequestAuth` (or `request.auth.tenant_id` directly); `TenantContextMiddleware` still reads `scope["auth"].tenant_id` and sets the `current_tenant_id` ContextVar; the three storage-layer listeners are untouched; the `current_tenant_id` ContextVar value is still the per-request tenant slug.
- **The 401 wire shape.** `urn:novamoc:problems:tenant_not_resolved` keeps its leaf and status code. Only the trigger changes from "wrong bearer token" to "session missing/expired/invalid."
- **The OpenAPI mount, the problem-details rendering pipeline, the schema-change-log shape, the event-log shape, the HLC ordering, the LWW fold.** Untouched.
- **The `SchemaController` and `EventsController` route tables.** No route paths change; no payload shapes change; no response shapes change.
- **The autouse `tenant` fixture's contract** to test code that doesn't care: it still sets `current_tenant_id` to `"t1"` (or whatever the test parametrizes). The fixture's implementation gains a small step (seed a real `tenants` row before yielding) so the FK constraint from `user_tenant_memberships` doesn't trip in the rare test that exercises both.

## Open design questions

These are the decisions I'd surface if I were not under "work without stopping" — flagging them in-spec so a reviewer can redirect rather than discover late:

1. **`Set-Cookie: Secure` heuristic.** Settings default `session_cookie_secure=False` so dev over `http://localhost` works; production deployments set `NOVAMOC_AUTH_SESSION_COOKIE_SECURE=true` explicitly. Alternative: derive from `docs_base_url`'s scheme. Currently choosing the explicit setting because the `docs_base_url` is a problem-details concern and overloading it is unrelated.
2. **Username case-folding.** The spec says NFKC + lowercase at write time. The alternative — case-sensitive usernames — matches Unix tradition but lets `Admin` ≠ `admin` enable phishing-ish impersonation. Choosing case-folding for safety; tracked if anyone wants to revisit.
3. **`POST /auth/login` returns 204, not the principal.** Forces the SPA to call `GET /auth/me` after login to discover the user. The trade-off is one extra round-trip on login for the simplicity of "`me` is the single source of truth." Acceptable for a same-origin SPA.
4. **CLI lives under `novamoc.cli`, mounted via `pyproject.toml [project.scripts]`.** Alternative: extend `just` recipes. Choosing a real CLI because the operator-side commands (`tenant create`, `user create`, ...) are the production write path, not just dev convenience.
