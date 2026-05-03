---
status: accepted
date: 2026-05-03
category: transport
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-016: RFC 9457 Problem-Details as the API Error Envelope

## Context and Problem Statement

The schema endpoint (ADR-013) currently returns errors as an ad-hoc JSON envelope (`{error, code, message, ...extras}`) — three top-level fields with overlapping concerns and untyped extension keys. As more endpoints come online they will all need an error contract; we'd rather not propagate the ad-hoc shape across the API. Should we adopt a standard error envelope, and if so which one?

## Decision Drivers

* Stability of the failure-mode identifier — the part clients branch on must not change when copy or formatting does.
* OpenAPI fidelity — the contract should be fully expressible in the generated OpenAPI document so client codegen sees typed fields, not a dictionary.
* Standard, recognizable shape over a project-specific invention — reduces the documentation burden on every consumer.
* Built-in framework support — avoid maintaining a custom rendering layer.
* Migration cost — no client SDKs exist yet, so the cost of switching now is local to the server. Migrating later means coordinating with downstream consumers.

## Considered Options

* RFC 9457 problem-details (`application/problem+json`)
* Keep the ad-hoc `{error, code, message, ...extras}` envelope
* JSON:API error objects

## Decision Outcome

Chosen option: **RFC 9457 problem-details**, because it provides a standard, well-known shape with explicit slots (`type`, `title`, `status`, `detail`, `instance`) plus a formal extension mechanism (§3.2) — the same roles the ad-hoc envelope's fields play, but with a recognizable schema and a dedicated media type. Litestar ships `ProblemDetailsPlugin` and `ProblemDetailsException`, so adoption costs no custom rendering code: a single `exception_to_problem_detail_map` registered at the app level converts typed domain exceptions at the API edge, and adding a new endpoint's exception is one row in that map.

The ad-hoc envelope's `error` category was always derivable from HTTP status; its `code` field was the only thing clients actually branched on, and that role transfers cleanly to the leaf segment of the `type` URI. JSON:API errors are heavier (they assume a `data`/`errors` document model novaMOC doesn't otherwise use) and recognized in a narrower community. Keeping the ad-hoc envelope was the cheapest option *today* and the most expensive *later*, once SDKs exist; we make the change now while the cost is bounded.

**Field mapping.** The ad-hoc envelope is *adapted* into RFC slots, not carried alongside:

* `error` is dropped — HTTP `status` is the category.
* `code` becomes the leaf of `type` (e.g., `urn:novamoc:problems:name_reserved`). Clients branch on the leaf.
* `message` → `detail`.
* New `title` — short, fixed string per code (§3.1).
* New `instance` — `urn:uuid:<uuid4>` per occurrence, for log correlation.
* Per-error extras stay as top-level keys, formally §3.2 extension members.

The type-URI base is currently a non-reachable URN (`urn:novamoc:problems:<code>`); §3.1 explicitly permits opaque URIs. Issue #13 tracks the eventual replacement with a published per-code documentation URL — a non-breaking change because clients branch on the leaf, not the host.

### Consequences

* Good, because every endpoint inherits one rendering layer; adding a new endpoint with new failure modes means one converter, not a fresh exception-handling stack.
* Good, because the `instance` field gives every error occurrence an opaque identifier for log correlation, which the ad-hoc envelope did not carry.
* Good, because the wire shape is fully documentable in OpenAPI under a typed schema, which generated clients can render directly.
* Bad, because `Content-Type` for 4xx/5xx flips from `application/json` to `application/problem+json`; clients that hard-coded `application/json` parsing on errors break. Tolerable today because no clients exist yet.
* Bad, because clients parse the leaf segment of `type` instead of a top-level `code` field — slightly less ergonomic but RFC-conformant.

### Confirmation

* Controllers' `responses=` mappings reference the `ProblemDetails` msgspec struct with `media_type="application/problem+json"`, so the generated OpenAPI documents the runtime content-type and the field shape consistently.
* End-to-end tests on the schema endpoint assert content-type and body shape on every error path (`tests/schema/test_endpoint_e2e.py`, `tests/schema/test_app_wiring.py`).
* Adding a new typed exception requires registering a converter in the app-level `ProblemDetailsConfig.exception_to_problem_detail_map`; an unmapped exception falls through to Litestar's default `HTTPException` rendering, which is plainly distinguishable from the problem-details shape in tests.

## More Information

* [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html).
* Migration tracked in issue #8; review and discussion on PR #11.
* Issue #13 — replace placeholder URN with published docs URL once one exists.
