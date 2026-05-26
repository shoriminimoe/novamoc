# Auth Middleware Rewrite Design (M5.11)

## Status

Draft. Closes issue #92. Lands as a precursor commit on the same branch
as the M5.11 implementation; once the implementation merges, this spec
is the canonical record of *why* the four open implementation choices
landed where they did.

## Purpose & scope

ADR-017 pinned the dispatch contract for tenant resolution: every
request reaches handlers through one middleware that produces a typed
`Principal` (`scope["user"]`) and `RequestAuth` (`scope["auth"]`).
ADR-020 selected the credential format that lives behind that
contract: a server-side session cookie backed by
`SQLAlchemyAsyncSessionBackend`. M5.5–M5.10 landed the storage,
services, password hasher, and route handlers. **M5.11 is the swap:**
replace the hardcoded-token resolver from ADR-017's v1 with a
session-cookie resolver, mount the session middleware that gives
`request.set_session` / `request.clear_session` their teeth, and
rebuild the test fixture stack so existing schema/events e2e tests
authenticate by logging in instead of attaching a bearer header.

Lands in **one commit**. The resolver shape, middleware signature, and
conftest fixture all move together; any split leaves the test suite
red between commits. The 8-file file-count heuristic is exceeded by
design — the commit message records the single-conceptual-seam
rationale.

In scope:

- Full rewrite of `domain/accounts/_resolver.py`: the v1 bearer-token
  function becomes the v2 session-cookie function. Same swap point ADR-017
  designed for.
- `AuthenticationMiddleware.authenticate_request` becomes
  async-with-DB-access. It reads the session payload off
  `connection.session`, opens a fresh SQLAlchemy session via the
  plugin's `SQLAlchemyAsyncConfig.get_session()`, instantiates the two
  registry services, and forwards to the resolver.
- `asgi.create_app` mounts `ServerSideSessionConfig`'s middleware
  ahead of the authentication middleware, builds a `PasswordHasher`
  from `AuthSettings`, stashes it on `app.state`, and registers
  `AuthController` on the route handler list. The exclude pattern on
  the authentication middleware grows to cover `/auth/login`.
- `tests/conftest.py` drops the bearer-header default on `client`,
  adds a `dev_admin` fixture that seeds the canonical test tenant +
  user + membership via direct service calls, and rebuilds `client`
  to log in once on construction. An `unauth_client` fixture serves
  the rejection-path tests.
- Five `test_resolver_session.py` cases that pin the resolver's
  accept/reject behaviour.

Out of scope:

- The `/auth/login` / `/auth/logout` / `/auth/me` wire-level e2e
  coverage — that's M5.12 (issue #93), which depends on M5.11 ship.
- Bootstrapping: no `on_startup` hook, no seed function, no
  `dev_seed_default_admin` setting. The server stays
  environment-independent (ADR-020 §"No dev-only code in the server").
  Local bootstrap is the M5.15 `just bootstrap-dev` recipe.
- Schema/events read or write changes — only the *credential* changes;
  the handlers and dispatch are unchanged.
- The svelte SPA's session bootstrap — separate spec when the client
  side starts.
- Membership-switch / multi-tenant active-tenant negotiation. v1 reads
  `active_tenant_id` straight off the session payload set at login;
  there is no per-request switch.

## Substantive decisions already made (record, don't relitigate)

These ride forward unchanged from the issue brief:

- **Resolver shape.** `async resolve_principal_from_session(session_payload, users, memberships) -> tuple[Principal, RequestAuth]`. Raises `TenantResolutionError` for: missing session keys (either `user_id` or `active_tenant_id` absent); user does not exist; user is disabled (`user.disabled_at is not None`); membership for the active tenant is missing. Takes already-decoded services so the function itself is pure-ish and unit-testable without a fixture stack.
- **Session payload.** `{"user_id": "<uuid-str>", "active_tenant_id": "<uuid-str>"}`. Both UUIDs serialise as strings — Litestar's session backend handles dict/list/string/int natively, and stringifying at the session boundary keeps the JSON round-trip predictable across backends.
- **Cookie config.** HttpOnly, `SameSite=Lax`, `Secure` from `AuthSettings.session_cookie_secure`, key from `AuthSettings.session_cookie_name`, `max_age` from `AuthSettings.session_ttl_seconds`, `path="/"`. Defaults are production-safe (`Secure=True`); local HTTP dev opts out via env var (`NOVAMOC_AUTH_SESSION_COOKIE_SECURE=false`).
- **Middleware order in `asgi.create_app`.**

      [
          session_middleware,                          # 1. read/write cookie ↔ scope["session"]
          DefineMiddleware(                            # 2. read scope["session"] → scope["user"] / scope["auth"]
              AuthenticationMiddleware,
              exclude=r"^/(openapi|problems|auth/login)",
          ),
          TenantContextMiddleware(),                   # 3. read scope["auth"].tenant_id → ContextVar
      ]

  The session middleware must run before the authentication middleware so `connection.session` is available inside `authenticate_request`. The authentication middleware must run before `TenantContextMiddleware` so the contextvar mount has `scope["auth"]` to read.

- **`TenantContextMiddleware` is unchanged.** It still reads `scope["auth"].tenant_id` and calls `use_tenant(...)`. M5.2 already flipped the contextvar type from `str` to `uuid.UUID`; nothing on this path notices.
- **`app.state.password_hasher`.** Built once at `create_app` time from `AuthSettings` cost params and stashed on `State({"settings": s, "password_hasher": ...})`. The `_provide_password_hasher` DI provider in `AuthController` (M5.10) already reads from this slot; this spec wires the producer side.
- **No `on_startup` hook for seeding.** Environment-conditional bootstrap belongs in the M5.15 `just bootstrap-dev` recipe / production init container, not the server.

## Open implementation-time decisions resolved

### 1. How `AuthenticationMiddleware.authenticate_request` acquires the SQLAlchemy session

The middleware runs **before** route resolution, so the controller's `dependencies` map is not yet bound — DI cannot supply the session. Three options were considered:

1. **Open a fresh session via the plugin's `SQLAlchemyAsyncConfig.get_session()` context manager.** Chosen.
2. **Reach into the request-scoped session that `before_send_handler="autocommit"` will commit at response time.**
3. **Defer resolution by writing the session payload into `scope["state"]` and resolving inside a controller `before_request` hook.**

Chosen: option 1. The pattern is exactly what `SQLAlchemyAsyncSessionBackend` itself does internally (it calls `self.alchemy.get_session()` on every read), so the resolver's session has the same lifecycle as the backend's — `async with self.alchemy.get_session() as db_session: ...`, opened on entry, closed on exit, no leakage past the middleware call. The pattern is verified in `advanced_alchemy/extensions/litestar/session.py:252`.

Mechanics:

```python
async def authenticate_request(self, connection: ASGIConnection) -> AuthenticationResult:
    payload = connection.session  # dict, populated by SessionMiddleware
    plugin = connection.app.plugins.get(SQLAlchemyPlugin)
    async with plugin.config.get_session() as db_session:
        users = UserService(session=db_session)
        memberships = UserTenantMembershipService(session=db_session)
        principal, auth = await resolve_principal_from_session(
            payload, users=users, memberships=memberships,
        )
    return AuthenticationResult(user=principal, auth=auth)
```

Option 2 was rejected because the auth middleware runs *before* the controller, before `before_send_handler` has set up the request-scoped session — there is nothing on the scope to reach for yet. Option 3 was rejected because it puts authentication behind route resolution: an unauthenticated request to a non-existent route would 404, not 401, breaking the byte-identical 401-on-credential-failure contract ADR-020 cares about.

Lifecycle pin: the session opened inside `authenticate_request` does **not** participate in the autocommit hook; it commits or rolls back independently. The only writes the resolver performs are read-only `SELECT`s, so this is fine — no transactional dependency on the route handler exists.

`plugin.config` returns a `SQLAlchemyAsyncConfig` (we only register the async variant); `get_session()` returns an `_AsyncGeneratorContextManager[AsyncSession]`. We rely on the single-config invariant and pull `config` directly. If we ever register multiple SQLAlchemyAsyncConfigs (e.g. a separate read-replica), the resolver picks the first; that is acceptable until it isn't, and the issue can be revisited then.

### 2. Where `PasswordHasher` lives on the app

`app.state.password_hasher`, constructed once at `create_app` time:

```python
hasher = PasswordHasher(
    time_cost=s.auth.argon2_time_cost,
    memory_cost_kib=s.auth.argon2_memory_cost_kib,
    parallelism=s.auth.argon2_parallelism,
)
state = State({"settings": s, "password_hasher": hasher})
```

This matches the existing `State({"settings": s})` pattern in `asgi.py` (which `EventsController.dependencies` already pulls from for the HLC drift limit). `_provide_password_hasher` in `controllers/_auth.py` (M5.10) already reads `state.password_hasher` — this spec adds the producer.

The `PasswordHasher` is a frozen, slotted dataclass that constructs a fresh `argon2.PasswordHasher` on each call (`_inner()` in `_password.py:54`). The wrapper itself is cheap and effectively stateless, but `state` is the right home anyway: it is read on every login request and constructing the wrapper once at startup is one less allocation per request.

### 3. The `dev_admin` test fixture's exact write path

Direct service calls, in this order, against the per-test session:

1. `TenantService(session).repository.add(Tenant(id=DEV_TENANT_ID, display_name="Acme"))` — uses the repository's `add` directly so the UUIDv7 default is overridden by our pinned constant. The CLI never does this; the fixture is the *only* place that pins a specific tenant UUID, because the test suite needs deterministic `tenant_id` values across runs.
2. `UserService(session).create(data={"username": "admin", "password_hash": hasher.hash(DEV_PASSWORD)}, auto_commit=False)` — folds the username through `_fold_username` automatically. The hash is the *real* argon2id hash (with `_FAST` test parameters: `t=1, m=8 MiB, p=1`) so the login round-trip exercises the verify path end-to-end.
3. `UserTenantMembershipService(session).create(data={"user_id": user.id, "tenant_id": DEV_TENANT_ID}, auto_commit=False)` — picks up the v1 1:1 invariant check for free.
4. `await session.flush()` so the rows are visible to the AuthenticationMiddleware's fresh session (since the in-memory engine uses `StaticPool`, both sessions hit the same physical DB).

The fixture exposes the values the `client` fixture needs to log in:

```python
@dataclass(frozen=True, slots=True)
class DevAdmin:
    username: str
    password: str
    user_id: uuid.UUID
    tenant_id: uuid.UUID  # == DEV_TENANT_ID

@pytest.fixture
async def dev_admin(session: AsyncSession, settings: Settings) -> DevAdmin: ...
```

`DEV_PASSWORD` lives in `tests/_constants.py` next to `DEV_TENANT_ID` — same single-source-of-truth pattern. The fixture's `_FAST` hasher is built locally; `tests/accounts/test_handlers.py` already uses the same `(t=1, m=8 MiB, p=1)` parameters and we copy them rather than share to avoid a cross-test-file import dependency.

**Tenant fixture interaction.** `dev_admin` depends on `session`, which depends on `engine`. The autouse `tenant` fixture sets the contextvar to `DEV_TENANT_ID` for the test's duration — but the auth-registry tables are not tenant-scoped, so the contextvar value is irrelevant to the seed itself. The fixture works fine under the default ambient `tenant` value and does not need to override or skip it.

### 4. The `/auth/login` exclusion in the authentication-middleware regex

Current: `^/(openapi|problems)`. After: `^/(openapi|problems|auth/login)`.

Login is the bootstrap path — it *writes* the session that subsequent
requests will read, so an unauthenticated request to `/auth/login` is
exactly correct, not an error. The `exclude_from_auth=True` opt on the
handler decorator in `controllers/_auth.py:94` is already in place, but
the exclude-pattern bypass kicks in earlier (before route resolution),
which means a malformed request to `/auth/login` (e.g. wrong
Content-Type) gets a 400 from the standard validation pipeline rather
than a 401 from the auth middleware reading an empty session.

The session middleware itself runs for *every* request including
`/auth/login` — it has to, because login is the request that calls
`set_session`. There is no exclusion at the session-middleware layer.

`/auth/logout` and `/auth/me` are *not* in the exclude pattern: both
require an authenticated request. `logout` calls `clear_session`,
which is a no-op on an empty session, but the handler's
`request.user` is still typed `Principal` and a logged-out caller
should get a 401 rather than a no-op success.

## Code surface

Numbers below pin the count claim in the acceptance criteria.

### Modified (8)

- `src/py/novamoc/domain/accounts/_resolver.py` — full rewrite. The
  module-private `_TENANT_T1_DEV_TOKEN` constant and `resolve_tenant`
  function are deleted; `resolve_principal_from_session(session_payload,
  *, users, memberships) -> tuple[Principal, RequestAuth]` replaces
  them. Five failure paths, one error type.
- `src/py/novamoc/domain/accounts/_middleware.py` —
  `AuthenticationMiddleware.authenticate_request` becomes async with
  DB access. Opens a fresh session via
  `connection.app.plugins.get(SQLAlchemyPlugin).config.get_session()`,
  constructs `UserService` / `UserTenantMembershipService`, forwards
  to the new resolver. `TenantContextMiddleware` is unchanged.
- `src/py/novamoc/domain/accounts/__init__.py` — drop the
  `_TENANT_T1_DEV_TOKEN` symbol from the public surface (it does not
  exist after the swap). Add `Principal`, `PasswordHasher`,
  `UserAlreadyHasTenantError`, and `AuthController` to `__all__` so
  the package-level imports are stable for tests and `asgi.py`.
- `src/py/novamoc/domain/accounts/controllers/_auth.py` — wire a
  `SecretStr` `type_decoder` onto the controller so `LoginRequest`
  bodies decode end-to-end. M5.10 defined the matching `decode_hook`
  in `_payloads.py` but never registered it; the leftover surfaces
  here because M5.11 is the first commit where `/auth/login` is
  reachable through the live mount.
- `src/py/novamoc/asgi.py` — build a
  `SQLAlchemyAsyncSessionBackend(config=ServerSideSessionConfig(...),
  alchemy_config=alchemy_config, model=Session)` and mount it via
  `DefineMiddleware(SessionMiddleware, backend=backend)`; extend the
  authentication-middleware exclude regex; register `AuthController`;
  build the `PasswordHasher` from `s.auth` and add it to the `State`
  literal. The middleware list grows from 2 entries to 3; the route
  handler list grows by one (`AuthController`).
- `src/py/novamoc/db/_listeners.py` — small defensive pin: a
  module-level `_AUTH_LAYER_TABLE_NAMES = frozenset({"tenants",
  "users", "user_tenant_memberships", "sessions"})` constant. Today's
  column-presence heuristic already does the right thing (none of
  these tables carry a non-`registry_fk` `tenant_id` column), but the
  constant gives a future contributor one greppable place to verify
  intent if they add a new auth-layer table that *would* carry a
  tenant column.
- `tests/conftest.py` — drop the
  `from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN`
  import and the `c.headers["Authorization"] = ...` line in the
  `client` fixture. Add `dev_admin` and `unauth_client` fixtures.
  Rebuild `client` to depend on `dev_admin` and `unauth_client`; call
  `POST /auth/login` once on construction so all subsequent requests
  carry the session cookie.
- `tests/_constants.py` — add `DEV_USERNAME = "admin"` and
  `DEV_PASSWORD = "dev-admin-password"`.

### Created (1)

- `tests/accounts/test_resolver_session.py` — five cases pinning the
  resolver:
  1. Happy path — valid session → `(Principal(id=str(user_id), username="admin"), RequestAuth(tenant_id=DEV_TENANT_ID))`.
  2. Missing `user_id` key → `TenantResolutionError`.
  3. Missing `active_tenant_id` key → `TenantResolutionError`.
  4. Unknown user (id doesn't resolve to a row) → raises.
  5. Disabled user (`disabled_at != None`) → raises.
  6. Active tenant the user has no membership in → raises.

  (Six cases when counted — "missing user_id" and "missing active_tenant_id" are split because they exercise different absent-key branches.)

### Deleted (some)

- The existing `tests/accounts/test_resolver.py` keeps its name but
  its bearer-flavored cases are deleted alongside `_TENANT_T1_DEV_TOKEN`.
  In practice we *replace* the whole file with `test_resolver_session.py`
  rather than keeping both — single file per swap point.
- `tests/accounts/test_middleware.py` and
  `tests/accounts/test_tenant_context_middleware.py` lose their
  `_TENANT_T1_DEV_TOKEN` imports and their bearer-header attaches.
  They are rewritten to either use the rebuilt `client` fixture (which
  logs in) or build a tiny probe app inline with a session middleware
  + auth middleware stack.

## Testing strategy

Repo conventions apply: real in-memory aiosqlite, no DB mocks, asyncio auto mode.

### `tests/accounts/test_resolver_session.py` (new)

Pure unit tests against the in-memory `session` fixture. Each test
seeds the registry rows via direct service calls (`UserService`,
`TenantService`, `UserTenantMembershipService`), constructs the
service pair the resolver takes, builds a session payload dict, and
calls `resolve_principal_from_session(...)`. Asserts the
`(Principal, RequestAuth)` tuple or the raised exception. No
Litestar app, no middleware stack — the resolver's signature is
explicitly the swap point so we test it without ceremony.

### Existing schema / events / snapshot e2e tests — minimal mechanical edits

The conftest changes do the work: every existing e2e test currently
attaches the dev bearer header via the `client` fixture's
`c.headers["Authorization"] = ...` line. Once that line is replaced
with a `POST /auth/login` call on fixture construction, the same
tests pass unchanged — the cookie now travels with every request the
client makes, and the auth middleware resolves it the same way it
resolved the bearer token before.

Tests that exercised the *401 rejection* path (e.g.
`tests/schema/test_endpoint_e2e.py::test_post_schema_without_credentials_returns_401`)
flip to use `unauth_client` instead of mutating headers per-request.

### Cross-tenant isolation

The cross-tenant isolation suites (`tests/schema/test_cross_tenant_isolation.py` et al.) build their own sessions and call `use_tenant(...)` directly — they do not go through the HTTP stack and are unaffected by this change.

### `tests/accounts/test_middleware.py`

Rewritten to construct its own session-middleware + auth-middleware
stack against a tiny probe handler, log in via a synthesised session
write (`session.add(Session(session_id=..., data=msgspec.json.encode({"user_id": ..., "active_tenant_id": ...}), expires_at=...))`),
and assert `request.user` / `request.auth` populate.

The base-class contracts (`exclude` path pattern, `exclude_from_auth`
opt-key, OPTIONS bypass) keep their existing tests — the surface
hasn't changed, only `authenticate_request` has.

## ADR coordination

No ADR change. ADR-017 designed the swap point we're swapping through;
ADR-020 selected the credential format we're swapping in. Both are
Accepted and stay that way. ADR-020's `## Confirmation` section
already cites `tests/accounts/test_resolver_session.py` as a planned
artifact of M5.11 — this commit creates that file and closes the
confirmation loop.

ADR-017 §"Recorded tech debt" listed "Single hardcoded bearer token"
as the gap M5.11 closes. Issue #19 was already updated when ADR-020
landed; no further action.

## Recorded tech debt

- **No session inactivity timeout.** `max_age` is absolute. A user
  active in the SPA all day still gets logged out at the
  `session_ttl_seconds` boundary. The Litestar config field
  `renew_on_access=True` would address this; v1 keeps it `False` for
  simplicity. Already recorded under ADR-020 §"Consequences"; not a
  new debt item.
- **No background session GC scheduler.** Expired rows accumulate
  until `novamoc auth gc-sessions` runs. Already recorded under
  ADR-020; the CLI command (M5.13) is the operator escape hatch.
- **No CSRF token alongside the session cookie.** `SameSite=Lax`
  protects the common cases (cross-origin POST from a third-party
  site) but not all. The SPA is same-origin and not exposed
  third-party today; a CSRF token spec is the right follow-up when
  any non-SPA caller appears.
- **Single SQLAlchemyAsyncConfig assumption in the middleware.** The
  resolver calls `connection.app.plugins.get(SQLAlchemyPlugin)` which
  returns the only registered plugin. If a second config lands
  (read-replica, audit DB), the resolver picks one arbitrarily. Not a
  v1 concern; the wider work is a separate spec when multi-DB shows
  up.
- **Resolver timing side-channel.** `resolve_principal_from_session`
  issues 0/1/2 SELECTs depending on which check fails (malformed UUID
  short-circuits, unknown user adds one query, missing membership adds
  two). Every path renders the same `401 tenant_not_resolved` body, so
  ADR-020's anti-enumeration claim about *response bytes* holds, but
  per-path latency differs. Network jitter generally swamps the
  difference and v1 ships as-is; a defensible hardening step is to
  issue both queries unconditionally and fold the results — the right
  follow-up when we add login rate-limiting (also recorded under
  ADR-020 §"Consequences" as a non-shipped concern).

## Notable non-changes

- Route handler signatures across the schema, events, and snapshot
  domains. None of them change — they still read `request.auth` for
  the tenant id, which now travels through the cookie instead of the
  header. The dispatch tables and handler maps are untouched.
- The problem-details rendering pipeline. `TenantResolutionError`
  still subclasses `NotAuthorizedException`, still has its mapper
  registered in `asgi.create_app`, still renders as 401 with the
  same type-URI leaf.
- The `before_send_handler="autocommit"` hook. Continues to commit
  the controller's request-scoped session at response time. The
  resolver's transient session opened in the middleware is
  independent.
- The auth registry tables' tenant-scoping disposition. `users`,
  `tenants`, `sessions`, and `user_tenant_memberships` continue to
  short-circuit the storage listeners. The defensive pin in
  `_listeners.py` is documentation-as-code; the runtime behavior is
  unchanged.
- `tests/data/scenarios/` and `tests/data/loader.py`. Scenarios
  already key off `DEV_TENANT_ID` (UUID, since M5.2); the literal
  match with the `dev_admin` fixture's seeded tenant is by
  construction.
