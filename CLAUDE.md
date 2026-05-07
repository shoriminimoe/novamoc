# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

novaMOC is a local-first, multi-tenant maintenance-tracking app: Svelte SPA client (with WASM SQLite, ADR-003) + Python/Litestar server (SQLite via aiosqlite, ADR-004) joined by a hand-rolled event-sourced sync protocol (HLC ordering + per-field LWW). Architecture is fixed by the ADRs in `docs/adr/`; **read the relevant ADRs before making non-trivial changes** — they are load-bearing and define hard constraints. Open design work and execution plans live in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

**Pre-release status — breaking changes are fine.** novaMOC is unreleased and in active design. There are no external consumers of the wire format, env-var names, database schema, or Python API yet, so prefer the cleanest design over backward compatibility. Don't add deprecation aliases, "kept for compatibility" hedges, or migration shims for things that haven't shipped. When the surface stabilises the user will tell you to stop making breaking changes; until then, name things right the first time.

Two **distinct classes of data** with deliberately different handling (ADR-001):

- **Schema** (asset types / their fields, maintenance record types / their fields) — server-authoritative current state, cannot be edited offline (ADR-008). Per-tenant `schema_version` = the highest `seq` in `schema_change_log` for that tenant.
- **Data** (assets, maintenance records, field values) — bidirectionally synced via append-only event log (`event_log`); entity tables and `*_field_values` tables are projections folded by deterministic LWW (ADR-002, ADR-007, ADR-011, ADR-012).

The schema-change log is **command-grain** (one row per accepted `POST /schema`) and is **not** folded into the projection — the projection is mutated transactionally alongside the append. The data event log is **EAV-grain** and *is* the source of truth.

## Repo layout

- `src/py/novamoc/` — Python server package (uv build module-root).
  - `asgi.py` — `create_app()` factory used by Litestar/Granian.
  - `db/models/schema/` — server-authoritative meta-schema tables + `schema_change_log`.
  - `db/models/data/` — synced entity projections, `*_field_values` LWW projections, `event_log`.
  - `db/models/_mixins.py` — `TenantScopedMixin` (adds `tenant_id` PK column with `sort_order=-200` so the composite PK leads with `tenant_id`, ADR-014).
  - `db/_listeners.py` — three SQLAlchemy event listeners that enforce tenant scoping (issue #51); `db/_tenant_context.py` holds the request-scoped `current_tenant_id` ContextVar and `use_tenant` helper.
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

## Linting and the ratchet

Ruff is the linter; the rule set is broad (see `[tool.ruff.lint]` in `pyproject.toml`). A custom ratchet (`scripts/ratchet.py`, baseline `.ruff-ratchet.json`, recipe `just ratchet`) snapshots per-rule violation counts. **The ratchet is intentional friction** — it's the project's mechanism for staying disciplined about linter feedback. CI is green iff every rule's count is ≤ its baseline.

Allowed transitions:

- **Counts decrease** → run `just ratchet-update` to commit the lower baseline. Routine.
- **Counts unchanged** → no action.
- **Counts would increase** → fix the violations or carve out a justified ignore. **Bumping the baseline to absorb a regression should be uncommon** and only legitimate as a *consequence* of a per-line / module-level ignore that's been deliberated and documented. The bump and the ignore land together. If you can't articulate why the ignore is justified, you don't get the bump.

When ruff reports new violations:

1. **Read the rule.** `uv run ruff rule <code>` prints the rationale. Do this *before* deciding to ignore — most rules teach a real lesson and the fix is short.
2. **Try `ruff check --fix`.** Many rules (TC001/2/3, PT018, RSE102, etc.) come with safe autofixes that restructure the code correctly. **Don't use `--unsafe-fixes`** — those can change runtime behaviour (e.g. moving type-only imports under `if TYPE_CHECKING:` for classes that introspect annotations at runtime).
3. **Fix manually if no safe autofix.** Most lint output is a chance to learn the rule and improve the code, not a chore to suppress.
4. **Ignore as a last resort, scoped as narrowly as makes sense.** Choose the smallest scope that captures the legitimate exemption:
   - **Per-line:** `# noqa: <CODE>  # short rationale` — for one-off cases (e.g. an `S608` false positive on a non-SQL string).
   - **Module-level:** `# ruff: noqa: <CODE>` near the top of the file (after the docstring, before imports) with a comment explaining why the rule doesn't apply here. Use this when an entire file legitimately violates a rule.
   - **`[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`:** **only for glob patterns** (`tests/**/*.py`, `src/py/novamoc/db/models/**/*.py`). Specific-file paths belong in module-level inline ignores, where the rationale lives next to the code.
   - **`[tool.ruff.lint.ignore]`:** project-wide. Reserve for rules ruff itself recommends disabling (`COM812`, `ISC001`) or rules whose noise consistently outweighs the signal across the whole codebase (`S101` for tests).
   - **Targeted ruff config** (e.g. `[tool.ruff.lint.flake8-type-checking].runtime-evaluated-base-classes`): some rules have configuration knobs that exempt specific classes/decorators. **Prefer a targeted config knob over an ignore** when one applies — the rule keeps firing where it should, just not where the configured framework legitimately violates it.

If you notice the same per-line / module-level ignore appearing across many files for the same rule, **flag it for the user**: that's the signal to consider a glob `per-file-ignores` entry, a project-wide `ignore`, or a targeted ruff config knob. The decision to widen the scope of an ignore is one the user makes, not the assistant.

**Runtime-introspected annotations.** SQLAlchemy declarative models (`Mapped[T]`) and msgspec Structs introspect their field annotations at runtime, so TC001/2/3 must not move their type-only imports under `if TYPE_CHECKING:`. This is configured in `[tool.ruff.lint.flake8-type-checking].runtime-evaluated-base-classes` (`advanced_alchemy.base.UUIDAuditBase`, `DefaultBase`, `msgspec.Struct`). New introspecting frameworks added later go in that list rather than per-file ignores.

Plain `@dataclass` is **not** in `runtime-evaluated-decorators`. Field annotations on a regular dataclass don't need runtime resolution — `ClassVar` / `InitVar` are special-cased by `dataclasses` itself and ruff already handles them. So dataclass field types should move under `if TYPE_CHECKING:` like any other type-only import. If a `type Handler = Callable[...]`-style alias references those types, use the PEP 695 `type` statement (lazily evaluated) rather than `TypeAlias` (eagerly evaluated).

## Critical layering rule

**`src/py/novamoc/db/` must not depend on Litestar.** db-layer modules import only `advanced_alchemy.base` / `advanced_alchemy.types` — never `advanced_alchemy.extensions.litestar`. The Litestar-flavored extensions (`SQLAlchemyAsyncConfig`, `repository`, `service`) belong to web-facing code: `domain/**/services/`, `domain/**/controllers/`, `asgi.py`, and `tests/conftest.py`. Keeping db-layer storage-only is what lets us swap or test the storage layer independently.

## Tenant-scoping enforcement (issue #51)

Cross-tenant isolation is enforced structurally by three SQLAlchemy event listeners registered at `db/_listeners.py` import time. The listeners key off `current_tenant_id` (a `ContextVar` in `db/_tenant_context.py`) which `TenantContextMiddleware` (`domain/accounts/_middleware.py`) sets from `request.auth.tenant_id` for HTTP requests; tests use the `tenant` pytest fixture or `use_tenant` directly.

- **Layer 1** (`do_orm_execute`): auto-injects `tenant_id = <ctx>` on every ORM SELECT against a class with a `tenant_id` column. Has a fallback for aggregate transforms (e.g. `count()`) that empty `state.all_mappers` — adds the predicate directly on the Core `Select`. Fail-closed: raises `UnscopedQueryError` when no contextvar is set.
- **Layer 2** (`before_flush`): walks `session.new`; auto-stamps `tenant_id` from contextvar if unset, raises `CrossTenantWriteError` if explicit and disagrees. Does NOT walk `session.dirty` — UPDATE goes through Layer 3.
- **Layer 3** (`before_execute`): backstop for Core-level INSERT/UPDATE/DELETE. Rejects synced-table DML lacking a `tenant_id` predicate (UPDATE/DELETE) or VALUES key (INSERT). SELECTs are excluded — Layer 1 owns them.

Handler call sites consequently pass NO `tenant_id` for reads and creates (auto-handled). They DO pass it inside `item_id=(auth.tenant_id, req.entity_id)` for `update`/`delete` because the composite PK is the WHERE clause. The `SchemaChangeLogService.append`/`current_version` API takes no `tenant_id` arg — Layer 1 supplies the predicate.

Escape hatch: the `SKIP_TENANT_FILTER` execution option suppresses Layer 1 and Layer 3. Greppable, no production callers in v1.

Out of scope of these layers: raw `session.execute(text(...))` SELECTs and in-place `obj.tenant_id` mutation. No production code uses these patterns; if added in the future, audit them carefully — they bypass the structural enforcement.

## Schema endpoint (`POST /schema`)

This is the only fully implemented endpoint and the canonical example of how server-side request handling is structured. It is the **command** half of ADR-008 — schema reads are deferred to a separate spec. The 18 verbs (5–6 each across `asset_type`, `asset_type_field`, `maintenance_record_type`, `maintenance_record_type_field`) are enumerated in `domain/schema/_commands.py::SchemaCommand`.

Pipeline:

1. **Wire decode** — `domain/schema/_payloads.py` defines one `msgspec.Struct` per command, all subclasses of `_SchemaCommand` (which auto-derives a `type` discriminator tag from the snake-cased class name). The 18 structs form `SchemaRequest`, a discriminated union Litestar publishes as `oneOf` in OpenAPI. msgspec rejects unions of untagged Structs, so `activate_*` payloads are a single optional struct rather than `_Definition | _Empty` — see the docstring at the top of `_payloads.py` and the design spec for the rationale.
2. **Dispatch** — `_dispatch.py` holds a single explicit `_HANDLERS: dict[type, Handler]` table. Adding a verb means writing the handler in `_handlers/<entity_kind>.py` and adding **one row** to that table; the universe of accepted commands is one rg-able place.
3. **Handlers** — `_handlers/{asset_type,asset_type_field,maintenance_record_type,maintenance_record_type_field}.py` expose verb-named module-level functions (`create`, `activate`, `update`, `deactivate`, `clear`, `delete`). Each handler validates against current projection state, mutates with `auto_commit=False`, then appends one `schema_change_log` row. The Litestar `before_send_handler="autocommit"` commits the whole transaction at response time — handlers must not commit themselves.
4. **Services** — `domain/schema/services/` thin advanced-alchemy `SQLAlchemyAsyncRepositoryService` wrappers, plus `SchemaChangeLogService.append`. Aggregated by `_bundle.py::ServiceBundle` (a frozen dataclass) so handlers take one parameter instead of five. **Import `ServiceBundle` from `_bundle`, not from `_dispatch` or `_handlers`** — both of those import `_bundle`, so importing them creates cycles.
5. **Controller** — `controllers/_schema.py::SchemaController` mounts at `/schema` and wires service DI via `advanced_alchemy.extensions.litestar.providers.create_service_dependencies`. The same controller hosts `GET /schema` (the snapshot read — see "Schema read endpoint" below). Error rendering is the app-level `ProblemDetailsPlugin` registered in `asgi.create_app`: `SchemaError`, `msgspec.ValidationError`, and Litestar's `ValidationException` all render as `application/problem+json` per ADR-016. The OpenAPI doc moves to `/openapi` because the route owns `/schema`.

Errors are raised as typed `SchemaError` subclasses (`PayloadShapeError`, `ConflictError`, `EntityNotFoundError`) carrying an `ErrorCode` enum value (`name_reserved`, `parent_type_not_found`, `entity_not_found`, `payload_no_changes`, `invalid_payload_shape`). `status_code` is pinned by the subclass; the leaf segment of `type_uri` (= the code value) is what clients branch on. Per-error extras (`name`, `field`, ...) ride as top-level extension members per ADR-016.

`UNSET` vs `None` in update payloads is meaningful: msgspec `omit_defaults=True` drops `UNSET` fields when serializing to builtins, so absent-from-wire becomes "untouched" and explicit `null` becomes "write NULL." Don't conflate them.

## Schema read endpoint (`GET /schema`)

Counterpart to `POST /schema`, on the same controller. Returns the full per-tenant schema projection (asset types and maintenance record types with nested fields, including tombstones) plus the current `schema_version`, in one transactional snapshot. Response shape lives in `domain/schema/_read_payloads.py` (separate from command-side `_payloads.py`); `schema_version` is computed via `SchemaChangeLogService.current_version()` (`MAX(seq)` for the active tenant, defaulting to `0`).

The handler does NOT take a tenant id parameter. `TenantContextMiddleware` (mounted upstream of the controller, ADR-017) sets `current_tenant_id` from `request.auth.tenant_id`; Layer 1 of the tenant-scoping listeners (`db._listeners`) supplies the `WHERE tenant_id = ...` predicate on every read inside the handler, including the `current_version()` aggregate via the listener's get-final-froms fallback path.

ETag = `"<schema_version>"` (RFC 7232 quoted decimal); `If-None-Match` matching the current version short-circuits to `304 Not Modified` after only the cheap `MAX(seq)` query (no projection scan). Tombstoned (`active=false`) rows are included in the response — clients filter at read time per use case (ADR-008/ADR-009: events targeting `deactivate_*`-d fields are still valid).

## Data model conventions

- All synced tables (schema + data) are tenant-scoped. Projection tables compose `(TenantScopedMixin, UUIDAuditBase)` — composite PK `(tenant_id, id)` with `tenant_id` as the leading column so the implicit PK index serves per-tenant queries (ADR-014). Log/EAV tables (`schema_change_log`, `*_field_values`) compose `(TenantScopedMixin, DefaultBase)`. `event_log` is the lone exception — it keeps a sole `seq` PK with hand-declared non-PK `tenant_id` because SQLite's `INTEGER PRIMARY KEY AUTOINCREMENT` doesn't support composite PKs; the listeners' column-presence heuristic still enforces tenant scoping on it.
- `event_log` uses a globally monotonic `seq` BigInt PK with a `(tenant_id, seq)` index — clients consume `seq` as an opaque cursor (ADR-011), so cross-tenant gaps are fine. `schema_change_log` uses a composite `(tenant_id, seq)` PK with the per-tenant `seq` computed at insert time, so each tenant sees a dense `1, 2, 3, …` sequence — that `seq` is the user/API-visible `schema_version` ADR-009's catch-up flow walks. Both derive from `DefaultBase`, not the audit base — `received_at` / `committed_at` are the audit role for an append-only log.
- Schema entities (types and fields) carry `active: bool`. Tombstoned rows (`active=false`) stay in the table to keep the name reserved and support resurrection via `activate_*`. Name UNIQUE constraints apply across both states.
- Field-value projection tables (`asset_field_values`, `maintenance_record_field_values`) have no audit columns; rows are rebuildable from the event log and `hlc` is the projection's ordering key.
- Enums (`FieldDataType`, `EventOp`, `SchemaCommand`, `ErrorCode`, `Outcome`) are `StrEnum`. Mapped enum columns use `Enum(..., native_enum=False)`. The `schema_change_log.command` column is plain `TEXT`, not a DB enum, so adding a new command verb is a domain change rather than a migration.

## Testing conventions

- `tests/conftest.py` provides:
  - `engine` — function-scoped in-memory aiosqlite, all metadata `create_all`'d on first use.
  - `session` — function-scoped `AsyncSession` against `engine`; rolls back on teardown so tests are isolated.
  - `services` — `ServiceBundle` wired against `session`.
  - `seed(scenario, tenant_id="t1")` — load a `tests/data/scenarios.py` scenario into the per-test db.
  - `app` — a fresh Litestar with its own in-memory aiosqlite engine. Uses SQLAlchemy `StaticPool` so all queries (the plugin's request-scoped session, the autocommit handler, etc.) reach the same in-memory database; each function-scoped `app` gets its own engine and dies at fixture teardown.
  - `client` — `AsyncTestClient(app)` with the dev bearer token already attached to its default headers.
  - `tenant` — autouse fixture that wraps each test in `use_tenant("t1")` so the tenant-scoping listeners have a contextvar to read. Tests that need a different tenant use `@pytest.mark.parametrize("tenant", [...], indirect=True)` and declare `tenant: str` to read the value. Tests that must run with no tenant context opt out with `@pytest.mark.no_tenant`.
- **No mocks for the DB.** db-layer / handler / endpoint tests run against a real in-memory SQLite. This catches metadata/migration drift the way mocks can't.
- E2E HTTP tests in `tests/schema/test_endpoint_e2e.py` exercise status code → error code mappings; handler-level tests in `tests/schema/test_handlers_*.py` exercise the typed-exception contract directly. The cross-tenant isolation suite (`tests/schema/test_cross_tenant_isolation.py`) seeds equivalent rows under `t-a` and `t-b` and asserts that every service method scopes correctly. When adding behavior, prefer the most specific layer that proves the behavior.

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
