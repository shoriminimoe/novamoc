---
status: accepted
date: 2026-05-18
category: authentication
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-020: Authentication and Tenant Registry

## Context and Problem Statement

ADR-017 settled tenant resolution at the request envelope but deferred the credential format: "v1 hardcodes a single token in source. No rotation, expiry, or revocation. Acceptable for the dev period only." It also left `RequestAuth.user` populated as `None`, since no user model existed. The M5 milestone replaces the hardcoded constant with a real registry, populates the principal slot, and closes [issue #19](https://github.com/shoriminimoe/novamoc/issues/19).

The question is which credential format the SPA uses, what shape the principal and tenant registry take, and how the membership join behaves when a single user may eventually belong to several tenants.

## Decision Drivers

* **Instant revocation.** A compromised credential must be invalidatable without waiting for a TTL to elapse.
* **Anti-enumeration.** The login surface must not leak whether a username exists, is disabled, or has no tenant membership.
* **Environment-independent server behaviour.** Production and development run the same code; bootstrap differences live outside the server.
* **Swap-friendliness relative to ADR-017.** The dispatch contract that ADR-017 pinned should survive the credential-format change without touching handlers, services, or tests.
* **Multi-tenant forward compatibility.** The v1 membership invariant (one tenant per user) must not lock the schema into a shape that has to be migrated for v2's switch-tenant feature.

## Considered Options

* **Server-side session cookie via advanced-alchemy's `SQLAlchemyAsyncSessionBackend`** — chosen.
* **Stateless JWT in `Authorization: Bearer <token>`.**
* **JWT carried in a cookie.**

## Decision Outcome

Chosen option: **server-side session cookie via `SQLAlchemyAsyncSessionBackend`**, because the SPA is same-origin so it does not benefit from stateless tokens, an HttpOnly cookie avoids the XSS-readable-token risk that a JWT in JavaScript-accessible storage carries, and a server-side store enables instant revocation. Sessions land in the existing SQLite engine — no new datastore. `litestar-users` was considered and rejected (single maintainer, RC release, dictates the `users ↔ tenants` shape).

### Credential format

The cookie is HttpOnly, `SameSite=Lax`, and `Secure` when the deployment configures it. The session row carries the user id and is loaded on every request by the authentication middleware; logout deletes the row, so revocation is immediate.

### Principal vs. scope

A new `Principal` (frozen `msgspec.Struct` with `id: str` and `username: str`) lands on `scope["user"]`. The existing `RequestAuth` shape stays on `scope["auth"]`; only its `tenant_id` field type changes. Future fields on either struct (token id, scopes, `expires_at`, actor kind) extend them without changing the dispatch contract ADR-017 pinned.

### Tenant id type

Tenant ids become UUIDv7. Every `tenant_id: Mapped[str]` column on a tenant-scoped table flips to `Mapped[uuid.UUID]` in lockstep — `TenantScopedMixin`, `event_log`, `schema_change_log` — along with `RequestAuth.tenant_id` and the `current_tenant_id` `ContextVar`. Scenarios and the conftest's `"t1"` literal are replaced by fixed UUID constants. Pre-release: a one-time conversion is cheaper now than later with more call sites. Mixed typing (UUIDs in the registry, strings everywhere else) was rejected as a footgun.

### N-to-N membership with v1 invariant

A `user_tenant_membership` join table is N-to-N in the schema; v1 enforces a one-membership-per-user invariant at write time. `UserTenantMembershipService.create` rejects a second membership for an existing `user_id` with `UserAlreadyHasTenantError` (409 `user_already_has_tenant`). Login does not trip this check — by the time it runs, the user has zero or one membership. v2's switch-tenant feature relaxes the service-layer check; the table shape carries forward unchanged.

### No dev-only code in the server

There is no seed function, no `on_startup` hook, no `dev_seed_default_admin` setting. Bootstrap is via CLI in every environment — a `just bootstrap-dev` recipe locally, an init container running the same commands in production. The server's behaviour is environment-independent; the class of failure where someone forgets to flip a flag in production cannot exist.

### Anti-enumeration on login

Wrong password, unknown user, disabled user, and the 0-membership transient share one byte-identical 401 `login_failed` body. An attacker probing for valid usernames cannot distinguish them. The 409 `user_already_has_tenant` surface belongs to the membership-write path (CLI), not login.

### Password hashing

argon2id with OWASP-recommended defaults (`m=64 MiB`, `t=3`, `p=4`). Cost parameters are settings-driven so they can be tuned over time. `check_needs_rehash` runs after every successful verify; active users upgrade for free when the cost is rotated.

### Username case-folding

Usernames are NFKC-normalised and `casefold()`-ed at write time, so `Admin` and `admin` resolve to the same row (anti-impersonation). The trade-off is that case-sensitive distinct usernames are impossible — accepted, because case-sensitive identifiers in a login surface are a known phishing footgun.

### Login response shape

`POST /auth/login` returns `204 No Content`. The SPA reads `GET /auth/me` afterwards. This keeps one source of truth for "who am I now"; the extra round-trip is acceptable on a same-origin SPA.

### Consequences

* Good, because the dispatch contract ADR-017 pinned survives the credential-format change unchanged — only the resolver's contents differ.
* Good, because every error continues to render through the problem-details pipeline (ADR-016); the new `login_failed` and `user_already_has_tenant` codes are converter rows, not a new rendering layer.
* Good, because revocation is instant: deleting the session row logs the user out immediately, with no TTL to wait out.
* Good, because the server's behaviour is identical across environments; the production-only configuration drift class of bug is structurally absent.
* Good, because issue #19's read/write gating asymmetry is closed permanently — every request reaches handlers through the same authentication middleware.
* Bad, because there is no registration endpoint, no email-based password reset, no 2FA, no login rate-limiting, and no API tokens for CLI/automation (cookie-only). Each is its own future spec, tracked as recorded tech debt.
* Bad, because session inactivity timeout is absolute TTL only; long-lived sessions do not refresh on activity.
* Bad, because session garbage collection is opportunistic. `novamoc auth gc-sessions` is the operator escape hatch until a scheduler exists.
* Bad, because there is no switch-tenant UX in v1; the membership table is N-to-N but the service enforces 1:1.

### Confirmation

* `tests/accounts/test_resolver_session.py` (M5.11) will pin the session-resolver behaviour: a valid cookie populates `request.user` and `request.auth`; a missing, expired, or unknown cookie renders 401.
* `tests/accounts/test_login_e2e.py`, `tests/accounts/test_logout_e2e.py`, and `tests/accounts/test_me_e2e.py` (M5.12) will pin the wire contract — including the byte-identical 401 `login_failed` body across the four anti-enumeration cases and the `204 + GET /auth/me` flow.
* `tests/accounts/test_membership_service.py` (M5.4) will pin the v1 one-membership invariant: a second `create` for the same `user_id` raises `UserAlreadyHasTenantError` and the controller renders 409 `user_already_has_tenant`.

## More Information

* ADR-017 — extended by this ADR; the resolver swap is the credential-format gap ADR-017 deferred.
* ADR-014 — already superseded by ADR-017; cited here to complete the chain.
* ADR-008 — server-authoritative schema; the first consumer of the eventual `Guard` layer that will sit above this ADR's authentication.
* ADR-016 — RFC 9457 problem-details; the rendering pipeline `login_failed` and `user_already_has_tenant` plug into.
* Issue #19 — closed by this milestone's implementation, not by this ADR alone.
