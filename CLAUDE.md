# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

novaMOC is a local-first, multi-tenant maintenance-tracking app: Svelte SPA client (with WASM SQLite, ADR-003) + Python/Litestar server (SQLite via aiosqlite, ADR-004) joined by a hand-rolled event-sourced sync protocol (HLC ordering + per-field LWW). Architecture is fixed by the ADRs in `docs/adr/`; **read the relevant ADRs before making non-trivial changes** — they are load-bearing and define hard constraints. Open design work and execution plans live in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

Two **distinct classes of data** with deliberately different handling (ADR-001):

- **Schema** (asset types / their fields, maintenance record types / their fields) — server-authoritative current state, cannot be edited offline (ADR-008). Per-tenant `schema_version` = the highest `seq` in `schema_change_log` for that tenant.
- **Data** (assets, maintenance records, field values) — bidirectionally synced via append-only event log (`event_log`); entity tables and `*_field_values` tables are projections folded by deterministic LWW (ADR-002, ADR-007, ADR-011, ADR-012).

The schema-change log is **command-grain** (one row per accepted `POST /schema`) and is **not** folded into the projection — the projection is mutated transactionally alongside the append. The data event log is **EAV-grain** and *is* the source of truth.

## Repo layout

- `src/py/novamoc/` — Python server package (uv build module-root).
  - `asgi.py` — `create_app()` factory used by Litestar/Granian.
  - `db/models/schema/` — server-authoritative meta-schema tables + `schema_change_log`.
  - `db/models/data/` — synced entity projections, `*_field_values` LWW projections, `event_log`.
  - `db/models/_base.py` — `TenantScopedAuditBase` (composite PK `(tenant_id, id)`; tenant sorts first, ADR-014).
  - `domain/schema/` — `POST /schema` endpoint stack (commands, payloads, dispatch, handlers, services, controller). See "Schema endpoint" below.
- `src/js/web/` — Svelte 5 + Vite + Tailwind SPA (currently scaffolding only).
- `tests/` — pytest suite (currently schema endpoint only).
- `docs/adr/` — accepted/proposed architecture decisions (ADR-000 through ADR-016).
- `docs/superpowers/{specs,plans}/` — design specs and execution plans for in-progress features.
- `justfile` — top-level dev tasks.

## Commands

The Python project is managed by **uv** with Python 3.14. Most common commands run inside `uv run`.

```sh
uv sync                                   # install deps + dev deps from uv.lock
just                                      # list available recipes (= just --list --unsorted)
just serve                                # = uv run litestar --app novamoc.asgi:create_app run
just build-py                             # = uv build
just test                                 # composite: every language's test suite (currently test-py only)
just test-py                              # = uv run pytest
uv run pytest tests/schema/test_endpoint_e2e.py::test_post_schema_creates_asset_type
uv run pytest -k "name_reserved"          # filter by test name
just lint                                 # composite: lint-py (= uv run ruff check --fix)
just format                               # composite: format-py (= uv run ruff format)
just typecheck                            # composite: typecheck-py (= uv run ty check, env root ./src/py)
just check                                # composite: lint + format + typecheck + test
just clean                                # rm -r dist
```

Frontend (in `src/js/web/`): `npm run dev` (vite), `npm run build`, `npm run check` (svelte-check + tsc).

`pytest` runs in **asyncio auto mode** (`pyproject.toml [tool.pytest.ini_options]`), so async tests don't need `@pytest.mark.asyncio`.

## Critical layering rule

**`src/py/novamoc/db/` must not depend on Litestar.** db-layer modules import only `advanced_alchemy.base` / `advanced_alchemy.types` — never `advanced_alchemy.extensions.litestar`. The Litestar-flavored extensions (`SQLAlchemyAsyncConfig`, `repository`, `service`) belong to web-facing code: `domain/**/services/`, `domain/**/controllers/`, `asgi.py`, and `tests/conftest.py`. Keeping db-layer storage-only is what lets us swap or test the storage layer independently.

## Schema endpoint (`POST /schema`)

This is the only fully implemented endpoint and the canonical example of how server-side request handling is structured. It is the **command** half of ADR-008 — schema reads are deferred to a separate spec. The 18 verbs (5–6 each across `asset_type`, `asset_type_field`, `maintenance_record_type`, `maintenance_record_type_field`) are enumerated in `domain/schema/_commands.py::SchemaCommand`.

Pipeline:

1. **Wire decode** — `domain/schema/_payloads.py` defines one `msgspec.Struct` per command, all subclasses of `_SchemaCommand` (which auto-derives a `type` discriminator tag from the snake-cased class name). The 18 structs form `SchemaRequest`, a discriminated union Litestar publishes as `oneOf` in OpenAPI. msgspec rejects unions of untagged Structs, so `activate_*` payloads are a single optional struct rather than `_Definition | _Empty` — see the docstring at the top of `_payloads.py` and the design spec for the rationale.
2. **Dispatch** — `_dispatch.py` holds a single explicit `_HANDLERS: dict[type, Handler]` table. Adding a verb means writing the handler in `_handlers/<entity_kind>.py` and adding **one row** to that table; the universe of accepted commands is one rg-able place.
3. **Handlers** — `_handlers/{asset_type,asset_type_field,maintenance_record_type,maintenance_record_type_field}.py` expose verb-named module-level functions (`create`, `activate`, `update`, `deactivate`, `clear`, `delete`). Each handler validates against current projection state, mutates with `auto_commit=False`, then appends one `schema_change_log` row. The Litestar `before_send_handler="autocommit"` commits the whole transaction at response time — handlers must not commit themselves.
4. **Services** — `domain/schema/services/` thin advanced-alchemy `SQLAlchemyAsyncRepositoryService` wrappers, plus `SchemaChangeLogService.append`. Aggregated by `_bundle.py::ServiceBundle` (a frozen dataclass) so handlers take one parameter instead of five. **Import `ServiceBundle` from `_bundle`, not from `_dispatch` or `_handlers`** — both of those import `_bundle`, so importing them creates cycles.
5. **Controller** — `controllers/_schema.py::SchemaController` mounts at `/schema` and wires service DI via `advanced_alchemy.extensions.litestar.providers.create_service_dependencies`. The same controller hosts `GET /schema/{tenant_id}` (the snapshot read — see "Schema read endpoint" below). Error rendering is the app-level `ProblemDetailsPlugin` registered in `asgi.create_app`: `SchemaError`, `msgspec.ValidationError`, and Litestar's `ValidationException` all render as `application/problem+json` per ADR-016. The OpenAPI doc moves to `/openapi` because the route owns `/schema`.

Errors are raised as typed `SchemaError` subclasses (`PayloadShapeError`, `ConflictError`, `EntityNotFoundError`, `TenantNotFoundError`) carrying an `ErrorCode` enum value (`name_reserved`, `parent_type_not_found`, `entity_not_found`, `payload_no_changes`, `invalid_payload_shape`, `tenant_not_found`). `status_code` is pinned by the subclass; the leaf segment of `type_uri` (= the code value) is what clients branch on. Per-error extras (`name`, `field`, `tenant_id`, ...) ride as top-level extension members per ADR-016.

`UNSET` vs `None` in update payloads is meaningful: msgspec `omit_defaults=True` drops `UNSET` fields when serializing to builtins, so absent-from-wire becomes "untouched" and explicit `null` becomes "write NULL." Don't conflate them.

## Schema read endpoint (`GET /schema/{tenant_id}`)

Counterpart to `POST /schema`, on the same controller. Returns the full per-tenant schema projection (asset types and maintenance record types with nested fields, including tombstones) plus the current `schema_version`, in one transactional snapshot. Response shape lives in `domain/schema/_read_payloads.py` (separate from command-side `_payloads.py`); `schema_version` is computed via `SchemaChangeLogService.current_version(tenant_id=...)` (`MAX(seq)`, defaulting to `0` for empty tenants).

`tenant_id` is gated by `KNOWN_TENANT_IDS` in `novamoc/config.py` — currently a hardcoded `frozenset({"t1"})` dev stub tracked by issue #19. Unknown tenants → 404 `tenant_not_found` with the offending value as a problem-details extension. **`POST /schema` is deliberately NOT gated** by this registry — that asymmetry will disappear when a real tenant registry lands.

ETag = `"<schema_version>"` (RFC 7232 quoted decimal); `If-None-Match` matching the current version short-circuits to `304 Not Modified` after only the cheap `MAX(seq)` query (no projection scan). Tombstoned (`active=false`) rows are included in the response — clients filter at read time per use case (ADR-008/ADR-009: events targeting `deactivate_*`-d fields are still valid).

The `app` test fixture in `tests/conftest.py` derives a per-test in-memory SQLite URI from `request.node.nodeid` so the empty-tenant ETag test sees `etag: "0"` regardless of sibling tests' POSTs (`cache=shared` would otherwise survive across function-scoped fixtures within one process).

## Data model conventions

- All synced tables (schema + data) are tenant-scoped. Most projection rows derive from `TenantScopedAuditBase` — composite PK `(tenant_id, id)` with `tenant_id` as the leading column so the implicit PK index serves per-tenant queries (ADR-014).
- `event_log` uses a globally monotonic `seq` BigInt PK with a `(tenant_id, seq)` index — clients consume `seq` as an opaque cursor (ADR-011), so cross-tenant gaps are fine. `schema_change_log` uses a composite `(tenant_id, seq)` PK with the per-tenant `seq` computed at insert time, so each tenant sees a dense `1, 2, 3, …` sequence — that `seq` is the user/API-visible `schema_version` ADR-009's catch-up flow walks. Both derive from `DefaultBase`, not the audit base — `received_at` / `committed_at` are the audit role for an append-only log.
- Schema entities (types and fields) carry `active: bool`. Tombstoned rows (`active=false`) stay in the table to keep the name reserved and support resurrection via `activate_*`. Name UNIQUE constraints apply across both states.
- Field-value projection tables (`asset_field_values`, `maintenance_record_field_values`) have no audit columns; rows are rebuildable from the event log and `hlc` is the projection's ordering key.
- Enums (`FieldDataType`, `EventOp`, `SchemaCommand`, `ErrorCode`, `Outcome`) are `StrEnum`. Mapped enum columns use `Enum(..., native_enum=False)`. The `schema_change_log.command` column is plain `TEXT`, not a DB enum, so adding a new command verb is a domain change rather than a migration.

## Testing conventions

- `tests/conftest.py` provides `engine` (in-memory aiosqlite, all metadata `create_all`'d), `session`, `services` (`ServiceBundle` wired against that session), `app` (Litestar with shared-cache in-memory aiosqlite — `cache=shared&uri=true` so the plugin's separate engine reaches the same DB), and `client` (Litestar `AsyncTestClient`).
- **No mocks for the DB.** db-layer / handler / endpoint tests run against a real in-memory SQLite. This catches metadata/migration drift the way mocks can't.
- E2E HTTP tests in `tests/schema/test_endpoint_e2e.py` exercise status code → error code mappings; handler-level tests in `tests/schema/test_handlers_*.py` exercise the typed-exception contract directly. When adding behavior, prefer the most specific layer that proves the behavior.

## Skills, agents, and MCP servers

Prefer the specialized tooling below over generic Bash/Read/Edit when the task fits — these are configured for this repo and produce better results than rolling your own.

**Python (uv / ruff / ty).** This project uses uv as package manager (`pyproject.toml` + `uv.lock`), ruff as linter+formatter, and ty as type-checker (`[tool.ty.environment] root = ["./src/py"]`). For any of these tools, invoke the corresponding `astral:*` skill via the `Skill` tool: `astral:uv`, `astral:ruff`, `astral:ty`. They cover correct invocation, common flags, and project-config conventions.

**Svelte.** `src/js/web/` is a Svelte 5 + Vite app. The official Svelte MCP server is configured in `.mcp.json` and **must** be used for any Svelte work — it provides `mcp__svelte__list-sections` / `get-documentation` / `svelte-autofixer` / `playground-link`. When creating or editing `.svelte` / `.svelte.ts` / `.svelte.js` files, prefer the `svelte:svelte-file-editor` Agent (it auto-uses the MCP tools) or the `svelte:svelte-code-writer` and `svelte:svelte-core-bestpractices` skills. After autofixing, re-run the autofixer to confirm all issues are resolved.

**Process skills (use *before* writing code).** This repo plans work explicitly — see `docs/superpowers/specs/` and `docs/superpowers/plans/`. For non-trivial work follow the same flow:

- `superpowers:brainstorming` — before any creative work (new features, design decisions). Outputs feed a spec.
- `superpowers:writing-plans` — once you have a spec, write a step-by-step plan before touching code. Plans land in `docs/superpowers/plans/<date>-<slug>.md`.
- `superpowers:executing-plans` / `superpowers:subagent-driven-development` — for carrying a plan out, with review checkpoints between steps.
- `superpowers:test-driven-development` — rigid skill, applies to features and bug fixes alike. Pairs with this repo's "real DB, no mocks" testing rule.
- `superpowers:systematic-debugging` — rigid skill, use for any unexpected behavior before proposing a fix.
- `superpowers:verification-before-completion` — run before claiming work is done; this repo's CI surface is `pytest` + `ruff` + `ty` + `npm run check`.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — pair around the review boundary.

**Exploration agents.** For broad codebase searches that span ≥3 queries, dispatch the `Explore` agent rather than running Glob/Grep yourself — it preserves the main context window. Reserve `general-purpose` for genuinely open-ended research.

**CLAUDE.md upkeep.** Use `claude-md-management:revise-claude-md` after sessions that change architecture, conventions, or commands; `claude-md-management:claude-md-improver` for periodic audits.

## ADR pointers (read these when touching the relevant subsystem)

- ADR-000 — the ADR practice. To start a new ADR, copy `docs/adr/_template.md`; that template carries the section structure, required-vs-optional rules, status lifecycle, and writing guidance. ADRs 001–015 use the older four-section shape and are grandfathered.
- ADR-001 overall architecture — three components, two transports, two data classes.
- ADR-002 / ADR-011 / ADR-012 — event-sourced data + append-only EAV log + JSON-projected entity tables.
- ADR-005 / ADR-008 — schema-as-data, server-authoritative; the meta-schema tables and the command verbs.
- ADR-006 / ADR-007 — HLC ordering and per-field LWW fold (the same fold runs on server and clients).
- ADR-013 — HTTP and WebSocket transports both carry the same event protocol.
- ADR-014 — multi-tenancy via `tenant_id` columns in shared tables, pre-auth tenant comes from request body.
- ADR-016 — RFC 9457 problem-details: the API-wide error envelope (`application/problem+json`).

ADRs cite each other by number rather than recapping upstream facts; follow the same convention when adding new ones.
