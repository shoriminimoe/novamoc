---
status: accepted
date: 2026-05-04
category: multi-tenancy
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-017: Tenant Resolution from the Request Envelope

## Context and Problem Statement

ADR-014 deferred how the server reads the per-request `tenant_id`: "the tenant_id is taken from the client's hello message" — in practice, a body field on `POST /schema` and a URL path parameter on `GET /schema/{tenant_id}`. With more endpoints landing (data event push/pull, snapshot, sync), every body/path appearance becomes surface area that any future authentication change has to rewrite, and the read/write gating asymmetry tracked in [issue #19](https://github.com/shoriminimoe/novamoc/issues/19) compounds.

We need a single mechanism for tenant identification, symmetric across reads and writes, decoupled from request bodies, and shaped so the eventual swap to a real credential format does not ripple through every handler.

## Decision Drivers

* **One source of truth.** Tenant id should appear in exactly one place per request, not body *and* path *and* (soon) credential.
* **Swap-friendliness for credentials.** v1 uses a hardcoded constant; the contract between transport and handlers should not change when v2 reads a real bearer token from a registry.
* **Symmetry between reads and writes.** The asymmetry from issue #19 should disappear at the same time we settle the resolution mechanism.
* **Real rejection path from day one.** A 401 path that is testable now, not deferred behind "auth comes later."

## Considered Options

* **Tenant resolved from the request envelope by middleware** — chosen.
* **Tenant id as a URL path parameter on every endpoint.**
* **Tenant id as a body field on every command struct.**

## Decision Outcome

Chosen option: **tenant resolved from the request envelope by middleware**, because it pins the dispatch contract once and absorbs every future credential-format change inside one module without touching handlers, services, or tests. v1 ships a real credential check (a hardcoded bearer token), so the rejection path exists from day one; only the credential's *contents* — the token value, the lookup mechanism, the registry — are deferred.

**Principal vs. scope.** The framework's `AuthenticationResult` has two slots, `user` and `auth`. We put the active tenant on `auth`, not `user`, because in a multi-tenant model a single user may have access to multiple tenants but each request operates within exactly one. `user` carries the principal (stable across requests); `auth` carries the credential-derived scope (varies per request). v1's principal is degenerate (no user model yet) and the active scope carries only the tenant id; both grow as the registry lands.

**Handler-facing type.** Handlers take a typed `auth: RequestAuth` parameter (frozen `msgspec.Struct`), not a bare `tenant_id: str`. Future fields on the credential's scope (token id, scopes, expires_at, actor kind) extend the struct rather than the dispatch signature.

**Mechanism.** A subclass of Litestar's `AbstractAuthenticationMiddleware` parses the `Authorization: Bearer <token>` header, matches the token against a hardcoded constant, and returns `AuthenticationResult(user=None, auth=RequestAuth(tenant_id=...))`. Resolution failures raise `TenantResolutionError` (subclass of `NotAuthorizedException`), rendered as `401 application/problem+json` with the type-URI leaf `tenant_not_resolved` per ADR-016. The OpenAPI doc at `/openapi` is exempt; future explicitly-public routes opt out per-handler.

**Authentication, not authorization.** This ADR concerns *authentication* (who/what is the request). *Authorization* (per-action permissions like ADR-008's "schema edits are admin-only when roles land") will arrive as Litestar `Guard`s, layered on top.

### Row-scoping (re-stated from ADR-014)

Every row in every synced table — schema tables, entity projection tables, event log, field-value projection tables — carries a non-null `tenant_id` column. In projection tables, `tenant_id` is the leading column of the composite primary key. In the event log, tenant scoping is enforced by `UNIQUE (tenant_id, hlc)` and indexed by `(tenant_id, seq)`. Every query scopes by `tenant_id`. The subscriber registry (ADR-013) is keyed by tenant. A client is associated with exactly one tenant at a time; switching tenants requires a new client context.

ADR-014 is superseded by this ADR so the multi-tenancy story lives in one place.

### Consequences

* Good, because the dispatch contract is stable across credential-format swaps. The v2 resolver looks up the bearer token in a tenant table or external IdP and returns a richer `RequestAuth` (and a non-`None` user); nothing else changes.
* Good, because the read/write gating asymmetry from issue #19 disappears — every request goes through the same middleware before reaching any route handler.
* Bad, because v1 hardcodes a single token in source. No rotation, expiry, or revocation. Acceptable for the dev period only; tracked with the registry work in issue #19.
* Bad, because the OpenAPI bypass is a regex. When a real registry lands the bypass surface will likely grow (health, login); the regex is the natural extension point but it is not yet a structured allow-list.

### Confirmation

* `tests/accounts/test_resolver.py` pins the resolver's accept/reject behaviour against `Headers`.
* `tests/accounts/test_middleware.py` exercises the middleware end-to-end (valid bearer populates `request.auth`; missing bearer renders 401; the `/openapi` bypass and the per-route opt-out both reach handlers without populating `scope["auth"]`).
* End-to-end tests on both schema endpoints assert 401 `tenant_not_resolved` on unauthenticated requests.
* `_SchemaCommand` carries `forbid_unknown_fields=True`, so a client still sending the legacy body-side `tenant_id` fails loud as `invalid_payload_shape` (400).

## More Information

* ADR-014 — superseded by this ADR.
* ADR-008 — server-authoritative schema; the schema endpoint stack is the first consumer of the new dispatch contract.
* ADR-016 — RFC 9457 problem-details; the rendering pipeline this ADR plugs into.
* Design spec: `docs/superpowers/specs/2026-05-04-tenant-resolution-middleware-design.md`.
* Implementation plan: `docs/superpowers/plans/2026-05-04-tenant-resolution-middleware.md`.
* Issue #19 — closed by this ADR's implementation.
