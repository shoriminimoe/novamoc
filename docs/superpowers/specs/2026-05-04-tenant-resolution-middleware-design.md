# Tenant Resolution Middleware Design

## Status

Draft

## Purpose & scope

Move `tenant_id` from "field on every API request body / URL path" to "value resolved from the request envelope by application middleware, attached to request state, and injected into handlers via Litestar DI." For v1 the resolver reads a bearer token off the `Authorization` header, matches it against a single hardcoded constant, and returns the tenant id (`"t1"`) on a hit; missing or unrecognized credentials are rejected with `401 tenant_not_resolved`. The load-bearing piece is the plumbing — handlers, services, and tests bind against the resolved value, so swapping the resolver later for a real per-tenant token registry is a single-file change.

The credential is a real check, not a placeholder. v1 ships exactly one valid token-to-tenant mapping; future versions will replace the constant with a registry lookup. The rejection path exists so we can write tests that exercise "tenant resolution fails" — the failure mode is part of the contract, not just a future-tense possibility.

This supersedes the *Sync protocol scoping* paragraph of ADR-014 ("Until auth exists, the tenant_id is taken from the client's hello message"). ADR-014 itself is superseded by ADR-017 (see *ADR coordination* below); the row-scoping decision carries through unchanged.

In scope:

- A `domain/accounts/` package containing the resolver, the Litestar middleware that calls it, the DI provider that hands the resolved value to handlers, and the typed exception raised on resolution failure.
- A new typed exception (`TenantResolutionError`) and its problem-details mapper, registered in `asgi.create_app` and the test `app` fixture.
- Removal of `tenant_id` from every `_SchemaCommand` payload struct and from the `GET /schema/{tenant_id}` URL path.
- Removal of `KNOWN_TENANT_IDS` from `novamoc/config.py` and `TENANT_NOT_FOUND` from `domain/schema/_errors.py` — the URL-path-based 404 disappears with the path; its semantic role is taken over by the new credential-based 401.
- A path-prefix bypass for `/openapi` so the docs UI is browsable without a token.
- All schema endpoint tests updated to (a) attach the dev bearer token by default, (b) omit `tenant_id` from request bodies, and (c) call the read endpoint at `/schema` (no path param).

Out of scope:

- A real per-tenant token registry. v1 hardcodes one token; future versions will load tokens from a database or external IdP.
- Token rotation, expiry, scopes, refresh, or any other credential lifecycle concern.
- Authorization beyond tenant scoping (per-user roles, per-endpoint permissions, schema-edit gates). ADR-008 already defers permissions; this spec does not unblock or change them.
- Anything client-side. The Svelte SPA does not yet talk to the server; once it does, it will need to know how to send its bearer token — that's a separate spec.

## HTTP contract changes

### Authorization header on every request

Every API request (except for the OpenAPI doc bypass, see below) must carry an `Authorization` header in the bearer scheme:

```
Authorization: Bearer <token>
```

For v1 the only valid token is the constant defined in `domain/accounts/_resolver.py` (e.g. `_TENANT_T1_DEV_TOKEN = "t1-dev-token"`). A request whose token matches resolves to tenant `"t1"`. Anything else — missing header, wrong scheme, mismatched case in `Bearer`, unknown token — yields `401 tenant_not_resolved`.

The token value is documented in the dev README (covered by the plan as a small README update) and treated as a development-only secret. Anyone with checkout access can read it; that is the intended trust model for the dev period.

### `POST /schema`

Request bodies drop the top-level `tenant_id` field on every command. The 22 `_SchemaCommand` subclasses each remove `tenant_id: str`. To keep the contract observable rather than silently permissive, `_SchemaCommand` gains `forbid_unknown_fields=True` so a request that still sends `"tenant_id": "..."` is rejected as `invalid_payload_shape` (400) — that's the cleanest migration signal for any client that was constructed against the old shape.

Wire example (after):

```http
POST /schema
Authorization: Bearer t1-dev-token
Content-Type: application/json

{
  "type": "create_asset_type",
  "entity_id": "11111111-1111-1111-1111-111111111111",
  "payload": {"name": "Truck"}
}
```

Response shape is unchanged.

### `GET /schema/{tenant_id}` → `GET /schema`

The path parameter is removed; the controller's read handler binds against the DI-injected `TenantContext` instead, reading `tenant.tenant_id` where the path param used to feed in. ETag/`If-None-Match` semantics are unchanged. The 404 `tenant_not_found` failure mode disappears with the path param — there is no longer a way for a client to ask about a tenant other than its own.

### New error: `tenant_not_resolved` (401)

Rendered through the existing `ProblemDetailsPlugin` per ADR-016.

| Status | `type` URI leaf       | Trigger                                                | Extension members |
|--------|-----------------------|--------------------------------------------------------|-------------------|
| 401    | `tenant_not_resolved` | Missing `Authorization` header, wrong scheme, or token does not match the configured constant. | none — the v1 resolver intentionally does not echo back what the client sent (avoids leaking internal token shape and prevents client code from branching on `extras` that will change once the registry lands). |

The single 401 covers all credential-failure variants so the wire contract has one failure mode for the credential check. When token formats grow (per-tenant tokens, expiry, scopes), additional codes can be introduced; v1 keeps it to one.

### Errors removed

| Removed                | Reason                                                                                              |
|------------------------|-----------------------------------------------------------------------------------------------------|
| `tenant_not_found` (404) | The only path that produced it was a URL-supplied tenant id that didn't match `KNOWN_TENANT_IDS`. With the path gone, a client cannot reference an unknown tenant; the resolved tenant is always known by construction. The credential-failure case is `tenant_not_resolved` (401), which is semantically distinct (the request never even produced a tenant id, vs. it produced one we don't recognize). |

`ErrorCode.TENANT_NOT_FOUND`, the matching `_DEFAULT_MESSAGES` entry, the `_TITLES`/`_STATUS_CODES` rows in `_problem_details.py`, and the `TenantNotFoundError` subclass all delete in lockstep.

### OpenAPI docs bypass

The OpenAPI doc at `/openapi` (and any sub-paths Litestar serves under it for Swagger UI / Elements / Stoplight) is exempt from the credential check so a developer can browse the docs without supplying a token. The bypass uses Litestar's built-in `ASGIMiddleware.exclude_path_pattern` class attribute (a regex matched against the resolved route handler's paths), so it composes with the framework's own short-circuit logic rather than re-implementing path matching:

```python
class TenantMiddleware(ASGIMiddleware):
    exclude_path_pattern = "^/openapi"
    ...
```

When a real tenant registry lands, this pattern is the natural place to extend with other unauthenticated routes (health, login).

## Tenant resolution mechanism

### TenantContext

The value the middleware produces and the DI layer hands to handlers is a `TenantContext` — a frozen `msgspec.Struct` defined in `src/py/novamoc/domain/accounts/_context.py`:

```python
import msgspec

class TenantContext(msgspec.Struct, frozen=True):
    tenant_id: str
```

For v1 the only field is `tenant_id`. The struct exists now (rather than after the next swap) because the handler boundary is the most expensive thing to refactor: 22 command handlers and one read handler each take this value as a parameter. Picking the richer shape now means future additions (e.g. `user_id`, `scopes`, `actor_kind`) extend the struct without touching the handler signatures or the dispatch contract.

`frozen=True` is deliberate: a request-scoped context that handlers receive should not be mutable from inside a handler; a downstream change to scopes or actor identity should be a new context, produced by middleware on the next request.

### Resolver function

Pure function, signature:

```python
from litestar.types import Scope
from novamoc.domain.accounts._context import TenantContext

def resolve_tenant(scope: Scope) -> TenantContext:
    """Return the TenantContext for this request, or raise TenantResolutionError."""
    ...
```

Lives in `src/py/novamoc/domain/accounts/_resolver.py`. v1 implementation: extract the `Authorization` header from `scope["headers"]` (a list of byte-tuples in ASGI), expect a `Bearer ` prefix (case-sensitive scheme name per RFC 6750), strip it, compare the remainder to the constant `_TENANT_T1_DEV_TOKEN`. On match, return `TenantContext(tenant_id="t1")`; on any failure (header absent, wrong scheme, value mismatch), raise `TenantResolutionError`.

The resolver is the swap point. The v2 resolver will look up the bearer token in a tenant table and build a richer context — same return type, more fields populated. Middleware and DI do not change.

### Middleware

`src/py/novamoc/domain/accounts/_middleware.py` defines a Litestar `ASGIMiddleware` subclass — Litestar's recommended subclassing API since 2.15 ([docs](https://docs.litestar.dev/latest/usage/middleware/creating-middleware.html#creating-middleware)). The class declaratively excludes the OpenAPI docs path via the built-in `exclude_path_pattern` attribute and implements `handle`:

```python
from litestar.middleware import ASGIMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send

class TenantMiddleware(ASGIMiddleware):
    exclude_path_pattern = "^/openapi"

    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        scope.setdefault("state", {})["tenant"] = resolve_tenant(scope)
        await next_app(scope, receive, send)
```

`resolve_tenant` may raise `TenantResolutionError`; that exception propagates out of `handle` and is caught by the application's `exception_handlers` map, which the `ProblemDetailsPlugin` populates with the new `TenantResolutionError → tenant_resolution_error_to_problem_details` mapper. Litestar 2.21's exception-handling stack catches middleware-raised exceptions the same as route-handler-raised exceptions; this is verified empirically in the spec's research and pinned by the unit test described under *Testing*.

The middleware is registered once at app construction (`Litestar(middleware=[TenantMiddleware()])`); the `ASGIMiddleware` docstring is explicit that subclasses should be stateless across requests, so `_TENANT_T1_DEV_TOKEN` lives on the resolver module and not on the middleware instance.

The middleware does not consume the request body. It runs before route resolution and acts only on headers and path.

### DI provider

`src/py/novamoc/domain/accounts/_di.py` exposes:

```python
async def provide_tenant(request: Request) -> TenantContext:
    return request.state.tenant
```

Registered alongside the existing service dependencies in `SchemaController.dependencies` (and any future controller's `dependencies` map) under the key `"tenant"`. Handlers take `tenant: TenantContext` as a parameter; the framework injects it.

The provider is trivial today and stays trivial. When the resolver populates more fields on the context, every handler that already takes `tenant: TenantContext` can read them — no signature change, no provider change.

### Handler signatures

The dispatch table's contract widens by one argument. Today:

```python
async def dispatch(services: ServiceBundle, request: Any) -> SchemaCommitOutcome
```

becomes:

```python
async def dispatch(services: ServiceBundle, tenant: TenantContext, request: Any) -> SchemaCommitOutcome
```

Each of the 22 command handlers gains `tenant: TenantContext` as a parameter and reads `tenant.tenant_id` in place of `req.tenant_id`. Handler internals are otherwise unchanged: same projection lookups, same change-log appends, same outcome construction. (When a handler eventually wants additional context fields, it reads them from `tenant.<field>` without a signature change.)

The read handler likewise drops `tenant_id` from its URL params and gains `tenant: TenantContext` from DI; otherwise it is unchanged.

## Code surface

**Created:**

- `src/py/novamoc/domain/accounts/__init__.py` — package marker; re-exports `TenantContext`, `TenantMiddleware`, `provide_tenant`, `resolve_tenant`, `TenantResolutionError` so consumers import from one path.
- `src/py/novamoc/domain/accounts/_context.py` — `TenantContext` frozen `msgspec.Struct` with `tenant_id: str`.
- `src/py/novamoc/domain/accounts/_resolver.py` — module-private constant `_TENANT_T1_DEV_TOKEN` and the `resolve_tenant(scope) -> TenantContext` function. The swap point.
- `src/py/novamoc/domain/accounts/_middleware.py` — `TenantMiddleware(ASGIMiddleware)` with `exclude_path_pattern = "^/openapi"`.
- `src/py/novamoc/domain/accounts/_di.py` — `provide_tenant(request) -> TenantContext`.
- `src/py/novamoc/domain/accounts/_errors.py` — `TenantResolutionError(Exception)` with a fixed message; rendered to 401 problem-details by the new mapper.
- `tests/accounts/__init__.py`, `tests/accounts/test_resolver.py`, `tests/accounts/test_middleware.py` — unit tests for the resolver (matches token returns `TenantContext(tenant_id="t1")`; rejects missing/wrong scheme/wrong token), the middleware (sets `scope["state"]["tenant"]` to the resolved context, propagates `TenantResolutionError` so the registered handler renders 401, bypasses `/openapi`), and the DI provider. Plus an end-to-end smoke test that hits a small probe handler through the `app` fixture and confirms `request.state.tenant.tenant_id == "t1"`.

**Modified:**

- `src/py/novamoc/asgi.py` — register `TenantMiddleware` in `Litestar(middleware=[...])`; add the new `TenantResolutionError → tenant_resolution_error_to_problem_details` entry in `exception_to_problem_detail_map`.
- `src/py/novamoc/api/_problem_details.py` — add the new mapper function `tenant_resolution_error_to_problem_details` (renders to status 401, type leaf `tenant_not_resolved`, title `"Tenant not resolved"`); delete the `TENANT_NOT_FOUND` rows in `_TITLES` and `_STATUS_CODES`.
- `src/py/novamoc/config.py` — delete `KNOWN_TENANT_IDS`.
- `src/py/novamoc/domain/schema/_payloads.py` — remove `tenant_id: str` from all 22 command structs; add `forbid_unknown_fields=True` to `_SchemaCommand`.
- `src/py/novamoc/domain/schema/_handlers/asset_type.py`, `_handlers/asset_type_field.py`, `_handlers/maintenance_record_type.py`, `_handlers/maintenance_record_type_field.py` — each handler signature gains `tenant: TenantContext` as the second positional argument; `req.tenant_id` references replaced by `tenant.tenant_id`.
- `src/py/novamoc/domain/schema/_dispatch.py` — `dispatch(services, tenant, request)`; the handler-table values' signatures match the new shape.
- `src/py/novamoc/domain/schema/_bundle.py` — `Handler` type alias updates from `Callable[[ServiceBundle, Any], Awaitable[SchemaCommitOutcome]]` to `Callable[[ServiceBundle, TenantContext, Any], Awaitable[SchemaCommitOutcome]]`.
- `src/py/novamoc/domain/schema/controllers/_schema.py`:
  - Add `tenant` to `SchemaController.dependencies` via `Provide(provide_tenant)`.
  - `apply_command` takes `tenant: TenantContext` and forwards it to `dispatch`.
  - `read_snapshot` becomes `@get("/")`; signature drops `tenant_id: str` from URL params, gains `tenant: TenantContext` from DI; the `KNOWN_TENANT_IDS` check and `TenantNotFoundError` raise are deleted.
- `src/py/novamoc/domain/schema/_errors.py` — delete `ErrorCode.TENANT_NOT_FOUND`, its `_DEFAULT_MESSAGES` row, and the `TenantNotFoundError` class.
- `tests/conftest.py`:
  - Register `TenantMiddleware` on the test `app` fixture.
  - Register `TenantResolutionError → tenant_resolution_error_to_problem_details` in the test `app`'s `exception_to_problem_detail_map`.
  - Construct the `client` fixture's `AsyncTestClient` with a default `headers={"Authorization": f"Bearer {DEV_TOKEN}"}` so existing tests pass without sprinkling the header through every call. Tests that exercise the rejection path override headers per-request.
- `tests/schema/test_endpoint_e2e.py`, `tests/schema/test_read_endpoint_e2e.py`, `tests/schema/test_app_wiring.py`, `tests/schema/test_handlers_*.py`, `tests/schema/test_payloads.py` — drop `tenant_id` from request bodies; switch read-endpoint URLs from `/schema/t1` to `/schema`; delete the `tenant_not_found` test cases.
- `tests/api/test_problem_details.py` — delete `test_schema_error_tenant_not_found_renders_404_with_extras`; add a new test for the 401 mapper.
- `README.md` — short note documenting the dev bearer token and how to send it with `curl`/HTTPie.

**Deleted (when their last reference goes):**

- `KNOWN_TENANT_IDS` constant.
- `ErrorCode.TENANT_NOT_FOUND`, `TenantNotFoundError`, the `_TITLES` / `_STATUS_CODES` rows for it.
- The `tenant_not_found` test in `tests/api/test_problem_details.py` and the e2e tests guarding the URL-path-based 404.

## Testing

Repo conventions apply: real in-memory aiosqlite, no DB mocks, asyncio auto mode.

**New test file `tests/accounts/test_resolver.py`** — direct unit tests, no app:

- Valid `Authorization: Bearer <token>` returns `"t1"`.
- Missing `Authorization` header raises `TenantResolutionError`.
- Wrong scheme (`Basic`, `Token`, `bearer` lowercased) raises.
- Bearer with empty token raises.
- Bearer with the wrong token value raises.
- Multiple tokens / extra whitespace handled defensively (the tightest reasonable acceptance: exact `"Bearer <single-token>"` shape, anything else rejects).

**New test file `tests/accounts/test_middleware.py`** — exercises the middleware via Litestar's testing client against a tiny probe app:

- Valid bearer → handler sees `request.state.tenant == TenantContext(tenant_id="t1")`, response is 200.
- Missing/invalid bearer → 401 `tenant_not_resolved` problem-details body.
- Bypass: `GET /openapi` is reachable without `Authorization` (no probe handler involved; just check that the doc endpoint returns its usual 200 and content type).

**Existing schema e2e tests** — minimal mechanical edits:

- The `client` fixture in `tests/conftest.py` now defaults to attaching the dev bearer token on every request, so existing tests pass once they drop the body field. (No per-test header threading required.)
- Drop `"tenant_id": _T` from every JSON body sent to `POST /schema`. With `forbid_unknown_fields=True` on `_SchemaCommand`, leaving stragglers in surfaces as a 400 the test will fail on — the migration is observable.
- Drop or repurpose the `_T` constant; the resolved tenant is `"t1"` regardless.
- Switch read-endpoint URLs from `f"/schema/{_T}"` to `"/schema"`.
- Add new e2e tests in `test_endpoint_e2e.py` and `test_read_endpoint_e2e.py` that exercise the 401 path on the real schema controller (an unauthenticated `POST /schema` and an unauthenticated `GET /schema` both render 401 `tenant_not_resolved`).
- Delete `test_get_schema_unknown_tenant_returns_404_problem_details` and `test_if_none_match_unknown_tenant_still_returns_404` — neither failure mode exists once the URL path is gone.

**Existing handler-level tests** (`tests/schema/test_handlers_*.py`) — these construct payload structs directly and call handlers. They drop `tenant_id=` from each payload literal, and update each `await <handler>(services, req)` call to `await <handler>(services, TenantContext(tenant_id="t1"), req)` to match the new signature. (A small fixture `tenant_context()` returning `TenantContext(tenant_id="t1")` is added to `tests/conftest.py` so test bodies stay focused.)

**Existing payload tests** (`tests/schema/test_payloads.py`) — assertions about the discriminated union's shape update to no longer expect a `tenant_id` field.

**Cross-tenant isolation** — out of scope for this spec. ADR-014's row-scoping decision carries through unchanged; tests that exercise it would belong with a follow-up that introduces a second tenant via the resolver. v1 has one tenant.

## ADR coordination

ADR-014 is superseded by a new **ADR-017: Tenant Resolution from the Request Envelope**. ADR-014's `## Status` flips from `Accepted` to `Superseded by ADR-017`. ADR-017 is written in the post-template MADR shape (YAML frontmatter, `Context and Problem Statement`, `Considered Options`, `Decision Outcome`, `Consequences`, `Confirmation`).

ADR-017 re-states the row-scoping decision verbatim from ADR-014 — that decision has not changed and we keep the multi-tenancy story in one place. The substantive change is the *Sync protocol scoping* paragraph: the new ADR records that the tenant identity is resolved from the request envelope by an `ASGIMiddleware` that reads a bearer token off `Authorization`, matches it against a hardcoded constant, builds a `TenantContext`, and stamps it onto `request.state.tenant`. The Considered Options section lists URL path parameter, body field, and request envelope, picking the third for one source of truth, swap-friendliness for credentials, and removal of the ADR-008 schema-write/read asymmetry tracked by issue #19. The handler-facing type (`TenantContext`) is also recorded as a decision point so that future fields (user id, scopes) extend the struct rather than the dispatch signature.

ADR-017 explicitly notes its v1 limitation: a single hardcoded token maps to a single tenant. The credential format (bearer scheme) is committed; the token value, the registry shape (constant vs lookup), and any token-lifecycle features (rotation, expiry, scopes) are deferred. The `Confirmation` section names two checks: the unit tests in `tests/accounts/test_resolver.py` pin the resolver's accept/reject behaviour, and the e2e 401 tests pin the wire contract.

## Recorded tech debt

- **Single hardcoded bearer token.** Tracked by the same issue #19 that today tracks `KNOWN_TENANT_IDS`. Issue text updates to reflect the new location of the stub (`domain/accounts/_resolver.py`) and the new disappearance criterion ("when a real per-tenant token registry is decided and `resolve_tenant` reads the token from a database table or external IdP").
- **No token rotation, expiry, or revocation.** v1 ships one token that lives forever. Replacing it requires a code change. Acceptable for the dev period; not for production. New issue captures this when ADR-017 lands.
- **Bypass pattern pinned to `^/openapi`.** Set as `exclude_path_pattern` on `TenantMiddleware`. When a real registry lands, this regex is the natural place to add other unauthenticated routes (health, login). Comment in the file points at the future call site.
- **Single 401 code for all credential-failure variants.** `extras` are deliberately empty in v1. When token formats grow, additional codes can split out (`token_expired`, `token_revoked`, `token_malformed`); v1 captures only the binary "resolved or not."

## Notable non-changes

- Row-scoping. Every synced table still carries `tenant_id`; every query still scopes by it. ADR-014's decision survives intact in ADR-017.
- The schema event log, the data event log, the projection tables, the HLC ordering, the LWW fold, the schema-change-log shape — all untouched.
- The problem-details rendering pipeline. The plugin, `ProblemDetails` struct, and `schema_error_to_problem_details` mapper continue to handle every other failure mode; the new 401 mapper plugs into the same `exception_to_problem_detail_map`.
- The OpenAPI mount at `/openapi`. The read handler's path becomes `/schema`, not `/`, so there is still no collision between the route and the docs mount. The bypass keeps the docs browsable without a token.
- `SchemaCommand` enum, `Outcome` enum, `SchemaCommitOutcome` shape. Tenant resolution does not touch the schema command vocabulary.
- The `tests/data/scenarios/` and `tests/data/loader.py` machinery. Scenarios already reference `tenant_id: "t1"` in their fixture JSON; that matches the resolver constant by construction.
