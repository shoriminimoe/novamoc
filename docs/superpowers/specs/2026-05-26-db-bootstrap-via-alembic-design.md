# Database Bootstrap via Alembic and the advanced-alchemy CLI

## Status

Draft. Lands as a precursor commit on the same branch as the
implementation. Once the implementation merges this spec is the
canonical record of *why* the bootstrap flow ended up where it did,
and ADR-021 (written as part of this work) is the durable
architectural record.

## Purpose & scope

Today `asgi.create_app` builds `SQLAlchemyAsyncConfig` inline with
`create_all=True` (env-defaulted), so the Litestar app's plugin
lifespan is what creates tables on startup — both in production and
in tests. The implicit contract is "boot the app, get tables." We are
inverting it: **the Litestar app always connects to an already-
initialized database**. Schema lives behind an Alembic migration tree
managed by the advanced-alchemy CLI (`alchemy upgrade head` and
friends), invoked outside the app's process lifecycle.

This work also lands **M5.15 (#96)**: the `just bootstrap-dev` recipe
that wraps `db-init` + the existing tenant/user CLI sequence, and
the README section that documents the full bootstrap and auth flow.
M5.15 was originally scoped as the milestone-closing step that only
needed the CLI; rolling it into this PR is mechanical because the
new `db-init` recipe is the precondition `bootstrap-dev` was always
implicitly waiting on. Closing #96 is the natural milestone-close
for this work.

In scope:

- New `src/py/novamoc/db/config.py` that owns
  `SQLAlchemyAsyncConfig` construction; exposes a module-level
  `alchemy_config` instance for the advanced-alchemy CLI's
  `--config` flag.
- `src/py/novamoc/db/migrations/` Alembic tree (`env.py`,
  `script.py.mako`, `versions/`) shipped inside the wheel.
- One baseline migration auto-generated from the current
  `metadata_registry`, reviewed, and committed.
- `create_app` refactor: stops constructing `SQLAlchemyAsyncConfig`
  inline, takes an optional `alchemy_config` keyword for test
  injection, drops the `create_all` plumbing.
- Startup gate: `on_startup` hook reads `alembic_version` and refuses
  to serve on mismatch.
- `just db-init` / `just db-revision <message>` / `just db-check`
  recipes wrapping the upstream CLI; `just check` adds `db-check`;
  `just bootstrap-dev` prepends `db-init`.
- Test conftest rewrite of the `app` fixture: build engine, run
  `metadata.create_all`, programmatic `alembic stamp head`, hand the
  engine to `create_app` via the new keyword.
- Deletions: `NOVAMOC_DB_CREATE_ALL` env var,
  `DatabaseSettings.create_all` field, the `s.db.create_all=True`
  literal in the test `settings` fixture.
- New ADR-021 capturing the four substantive decisions.
- CLAUDE.md: new "Database bootstrap" section pointing at ADR-021;
  the "Critical layering rule" section grows a second documented
  carve-out for `db/config.py`.
- **`just bootstrap-dev` recipe (M5.15 / #96):** idempotent wrapper
  that runs `db-init` then the existing tenant/user/membership CLI
  sequence. Lands as a single `just` recipe with `db-init` as a
  recipe dependency.
- **`README.md` dev-setup section (M5.15 / #96):** populates the
  currently-empty README with the project blurb and the bootstrap
  + auth flow (`just bootstrap-dev`, the CLI shape, SPA `/login`,
  curl cookie pattern, the `/openapi`-only-unauth note).
- **Final verification matrix run** as documented in #96, extended
  with `just db-init` and `just db-check`.

Out of scope:

- A `novamoc db ...` Click subgroup. The advanced-alchemy CLI is
  already the right surface; wrapping it in our own CLI adds drift
  with no payoff. `novamoc` CLI stays focused on tenant/user/auth.
- Squashing migrations. Pre-release churn means many small revisions;
  squash-to-baseline is a separate decision the user makes closer to
  first release.
- Production init-container manifests / systemd unit / Dockerfile
  changes. ADR-021 documents the *contract* (run `alchemy upgrade
  head` before the app starts); the actual deployment artifacts are
  downstream of whatever runtime hosts the app.
- Per-tenant or per-environment schema variations. One Alembic head
  for the whole project.
- Full README beyond the dev-setup section. Project description /
  architecture overview / contribution guide are separate.

## Substantive decisions already made (record, don't relitigate)

These rode forward from the brainstorming session and are settled:

- **Schema management is Alembic via the advanced-alchemy CLI.** The
  upstream `alchemy` CLI is the operator-facing surface
  (`alchemy upgrade`, `alchemy make-migrations`, `alchemy check`,
  `alchemy show-current-revision`, `alchemy stamp`, etc.). It is
  invoked directly by `just` recipes, init containers, and CI — never
  wrapped in our own Click CLI. Plain `create_all`-from-a-CLI was
  considered and rejected: pre-release schema churn is exactly when
  you want the *discipline* of migrations, even if the migrations
  themselves get squashed later.
- **Migrations live inside the package** at
  `src/py/novamoc/db/migrations/`, shipped in the wheel via uv_build's
  module-root. Production wheel installs find them by package path;
  no extra wheel-data entry. Aligns with the layering rule — Alembic
  has no Litestar dependency. Repo-root `./migrations/` was
  considered and rejected because shipping it would require an extra
  `[tool.uv.build-backend].data` entry without a clear benefit.
- **One baseline migration generated now.** `alchemy make-migrations
  -m "baseline"` against the current `metadata_registry` produces a
  single revision that creates every existing table. We review and
  edit it before commit (autogenerate misses rename intent,
  server-default semantics, and the field-order conventions our
  models care about). Empty `migrations/` tree was considered and
  rejected — the bootstrap-on-start contract is meaningless without a
  HEAD to upgrade to.
- **Startup gate fails fast.** `create_app` registers an `on_startup`
  hook that reads `alembic_version` and refuses to serve on mismatch
  (or missing table). Detects "forgot to run db-init" at process
  boot rather than at first SQL query. Tests are uniform with prod —
  the conftest stamps HEAD after `metadata.create_all` so the gate
  passes without ever running migrations.

## Resolved implementation choices

Settled during the design review:

- **`create_app(settings, alchemy_config=None)`** is the test
  injection seam. Production calls `create_app(settings)` and the
  function builds the config via `build_alchemy_config(settings)`;
  tests build the config themselves (so they can pre-populate the
  engine and stamp HEAD) and pass it through. Considered:
  reach-into-`app.plugins.get(SQLAlchemyPlugin)` after construction
  to discover the engine; rejected as uglier and harder to delete.
- **`just check` gates on `db-check` from day one** alongside ruff,
  format, typecheck, coverage, and ratchet. A model change without a
  matching migration fails the same gate that catches ruff
  violations, in the same loop the contributor already runs. CI
  inherits this via the existing `just check` invocation.
- **ADR-021 written as part of this work**, not deferred to CLAUDE.md
  only. The bootstrap contract is load-bearing for every future
  deployment and every contributor onboarding; an ADR is the right
  shape. CLAUDE.md gets the operational pointer; ADR-021 carries the
  rationale (why migrations, why in-package, why fail-fast).

## Architecture

Three actors with distinct responsibilities:

1. **The `alchemy` CLI** owns schema-as-it-exists-on-disk. It is
   invoked from operator hands, `just` recipes, init containers, and
   CI — always against a dotted-path resolvable
   `SQLAlchemyAsyncConfig` instance:

       uv run alchemy <verb> --config novamoc.db.config.alchemy_config

   This actor is the only thing that mutates schema. It is the only
   thing that knows about Alembic.

2. **The Litestar app** is a *consumer* of an already-initialized
   database. `create_app` constructs `SQLAlchemyAsyncConfig` with
   `create_all=False` (i.e. not set at all). An `on_startup` hook
   verifies the DB is at HEAD. Anything else is a startup failure.

3. **Tests** sidestep the migration tree entirely. The conftest's
   `app` fixture builds the engine, runs `metadata.create_all`
   against it (the same loop the existing `engine` fixture uses), and
   then programmatically stamps HEAD on the `alembic_version` table.
   This keeps the in-memory SQLite test path fast (no Alembic upgrade
   per test) while making the startup gate's invariant uniform across
   prod and tests.

## The seam: `src/py/novamoc/db/config.py`

A new db-layer module that owns one job: constructing
`SQLAlchemyAsyncConfig` from `Settings`. Shape:

```python
# src/py/novamoc/db/config.py
from importlib.resources import files
from advanced_alchemy.extensions.litestar import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
)
from sqlalchemy.pool import StaticPool

from novamoc.config import Settings


def _migrations_dir() -> str:
    """Resolve ``src/py/novamoc/db/migrations`` for both wheel and editable installs."""
    return str(files("novamoc.db") / "migrations")


def build_alchemy_config(settings: Settings) -> SQLAlchemyAsyncConfig:
    """Construct the per-app SQLAlchemyAsyncConfig.

    Single chokepoint for engine + Alembic wiring; consumed by
    ``create_app`` (production) and the test ``app`` fixture (which
    builds its own config so it can pre-populate the engine and
    stamp HEAD before the Litestar plugin's lifespan opens).
    """
    engine_config = (
        EngineConfig(poolclass=StaticPool) if settings.db.static_pool else EngineConfig()
    )
    return SQLAlchemyAsyncConfig(
        connection_string=settings.db.url,
        before_send_handler=settings.db.before_send_handler,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        engine_config=engine_config,
        alembic_config=AlembicAsyncConfig(script_location=_migrations_dir()),
    )


alchemy_config = build_alchemy_config(Settings())
"""Module-level instance for ``alchemy --config novamoc.db.config.alchemy_config``.

``Settings()`` reads env vars at import time. CLI invocations are
fresh processes so they pick up ``NOVAMOC_DB_URL`` etc. without
ceremony; the test process imports this transitively but does not
consume it (tests use ``build_alchemy_config(settings_fixture)``).
"""
```

`AlembicAsyncConfig`'s `version_table_name` defaults to
`"alembic_version"`, which is what the startup gate reads — no
override needed.

**Layering carve-out.** `db/config.py` imports
`advanced_alchemy.extensions.litestar.SQLAlchemyAsyncConfig`. The
Litestar plugin requires this subclass at registration time, and the
alchemy CLI also accepts the subclass (it polymorphs against the
base). Pulling in the base config would mean a second config-building
path for the plugin — strictly worse. This is the second documented
carve-out to the "db/ must not depend on Litestar" rule (alongside
`db/models/_auth/_session.py`'s `SessionModelMixin`). CLAUDE.md
"Critical layering rule" gets updated to list both.

## Migrations directory

`src/py/novamoc/db/migrations/`:

    migrations/
        __init__.py          # so importlib.resources can resolve it
        env.py               # generated by `alchemy init`, customized to use build_alchemy_config
        script.py.mako       # default Alembic template
        versions/
            __init__.py
            <rev>_baseline.py

`env.py` is customized to:

- Import `novamoc.db.models` so every model is registered on
  `metadata_registry` before `target_metadata` is consulted.
- Build the target metadata by unioning every metadata in
  `metadata_registry` (mirrors the test `engine` fixture's loop).
- Use `alchemy_config`'s engine for online mode; the offline path
  reads the same URL.

The baseline revision is generated by:

    uv run alchemy make-migrations \
        --config novamoc.db.config.alchemy_config \
        -m "baseline"

reviewed (rename intent, server defaults, index naming), and
committed alongside this work.

uv_build's `module-root = "src/py"` already covers package-resident
files, so `migrations/` ships in the wheel without additional config.

## CLI surface — `just` recipes wrap the upstream tool

Three new recipes:

```just
# Apply all pending migrations against $NOVAMOC_DB_URL.
db-init:
    uv run alchemy upgrade head --config novamoc.db.config.alchemy_config

# Generate a new revision from the current models.
db-revision message:
    uv run alchemy make-migrations --config novamoc.db.config.alchemy_config -m "{{message}}"

# CI gate: fail if models drift from the migration tree.
db-check:
    uv run alchemy check --config novamoc.db.config.alchemy_config
```

Existing recipes change:

- `just check` adds `db-check` to its dependency list
  (`check: lint format typecheck coverage ratchet db-check`).
- `just bootstrap-dev` prepends `just db-init` so a fresh local DB
  gets its schema before tenant/user seeding runs.
- `just serve` does *not* call `db-init` — the user-facing contract
  is that bootstrap is an explicit step. If the operator forgets, the
  startup gate fires.

Production deployments: an init container (or pre-start hook on the
process supervisor) runs the same `uv run alchemy upgrade head` step
before Granian starts. ADR-021 documents the contract; deployment
manifests are downstream.

## `just bootstrap-dev` (M5.15 / #96)

The recipe that closes M5.15 wraps `db-init` plus the existing
tenant/user CLI sequence. `db-init` is a recipe-level dependency
rather than an inline shell command so a contributor can run it
standalone (`just db-init`) without firing the full bootstrap:

```just
# Apply migrations, then create the dev tenant + admin user.
# Idempotent: skips when admin exists. Production runs the
# equivalent CLI commands in an init container.
bootstrap-dev: db-init
    #!/usr/bin/env bash
    set -euo pipefail
    if uv run novamoc user exists admin >/dev/null 2>&1; then
        echo "admin user already exists; nothing to do."
        exit 0
    fi
    tenant_id=$(uv run novamoc tenant create --display-name "Development" \
                | awk '{print $3}' | tr -d '.')
    echo "Created tenant $tenant_id."
    uv run novamoc user create admin --password admin
    uv run novamoc user add-to-tenant admin "$tenant_id"
    echo "Bootstrap complete. Login at /login with admin / admin."
```

`alchemy upgrade head` is idempotent (no-op at HEAD), so re-running
`just bootstrap-dev` after the first invocation finishes in the
short-circuit path. The `awk '{print $3}'` field index matches the
M5.13 CLI's `Created tenant <uuid>.` output verbatim (verified in
`cli.py:177`); if that format ever changes, the recipe breaks loudly
rather than silently miscapturing.

## `README.md` dev-setup section (M5.15 / #96)

The README is currently empty. This work writes the minimum that
covers #96's required content. Shape:

```markdown
# novaMOC

<one-paragraph project blurb, drawn from CLAUDE.md's "Repository"
intro: local-first multi-tenant maintenance-tracking app, Svelte SPA
+ Litestar server, event-sourced sync, pointer to docs/adr/.>

## Development setup

1. `uv sync` — install Python deps from `uv.lock`.
2. `just bootstrap-dev` — apply migrations, create the dev tenant
   `Development`, and provision the `admin` / `admin` user. Idempotent.
3. `just serve` — start the API on `http://localhost:8000`.
4. `cd src/js/web && npm install && npm run dev` — start the SPA.

Production deployments run the equivalent commands in an init
container (no environment-conditional code in the server).

### Adding more tenants / users from the CLI

    uv run novamoc tenant create --display-name "<Display Name>"
    uv run novamoc user create <username>
    uv run novamoc user add-to-tenant <username> <tenant-uuid>

## Authenticating against a running server

The auth cookie is HttpOnly and `SameSite=Lax`; the SPA never touches
the token directly.

**Browser:** navigate to `/login`. The layout's boot-time `/auth/me`
probe redirects unauthenticated requests to `/login` automatically.

**Scripts / curl:** persist the cookie jar:

    curl -c cookies.txt -X POST http://localhost:8000/auth/login \
        -H 'Content-Type: application/json' \
        -d '{"username": "admin", "password": "admin"}'
    curl -b cookies.txt http://localhost:8000/auth/me

`/openapi` is the only unauthenticated route; every other route
returns 401 `tenant_not_resolved` without a valid session.
```

The README is intentionally short. Project overview, architecture,
and contribution guides are separate work.

## Tests

The `app` fixture in `tests/conftest.py` changes shape:

```python
@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Litestar]:
    alchemy_config = build_alchemy_config(settings)
    engine = alchemy_config.get_engine()
    async with engine.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    # AlembicCommands.stamp is sync; it owns its own connection lifecycle
    # against the alchemy_config's engine.
    await asyncio.to_thread(AlembicCommands(alchemy_config).stamp, "head")
    yield create_app(settings=settings, alchemy_config=alchemy_config)
    await engine.dispose()
```

`AlembicCommands(alchemy_config).stamp("head")` is advanced-alchemy's
public wrapper that creates and populates the `alembic_version` table
with the script tree's HEAD revision. The call is sync, so the
conftest dispatches it via `asyncio.to_thread`. This is what makes
the startup gate succeed in tests without running any migration.

`create_app` gains an optional `alchemy_config` keyword:

```python
def create_app(
    settings: Settings | None = None,
    *,
    alchemy_config: SQLAlchemyAsyncConfig | None = None,
) -> Litestar:
    s = settings if settings is not None else Settings()
    cfg = alchemy_config if alchemy_config is not None else build_alchemy_config(s)
    ...
```

Production: `create_app(settings=s)` builds the config. Tests pass
the pre-populated one. The `engine` fixture (for direct-DB tests) is
unchanged — it doesn't go through `create_app` at all.

The `settings` fixture loses its `create_all=True` literal.

## Startup gate

In `create_app`, add an `on_startup` async hook that:

1. Opens a connection from the plugin's engine.
2. Reads the current revision via
   `MigrationContext.configure(conn).get_current_revision()`.
3. Reads the script tree's HEAD via
   `ScriptDirectory.from_config(alembic_cfg).get_current_head()`.
4. Raises `RuntimeError` on mismatch (including `None` from step 2,
   which means the `alembic_version` table is missing entirely).

The error message names the exact remediation:

    RuntimeError: Database schema at revision '<found>' but app expects '<head>'.
    Run: uv run alchemy upgrade head --config novamoc.db.config.alchemy_config

The hook is *always on*. Tests pass because their conftest stamps
HEAD; production passes because the init container ran
`alchemy upgrade head`; misconfigurations fail at boot.

## Deletions

The following surface goes away as part of this work:

- `NOVAMOC_DB_CREATE_ALL` env var.
- `DatabaseSettings.create_all` field.
- `s.db.create_all=True` in the test `settings` fixture.
- The `engine_config.create_all` argument in `create_app`'s inlined
  `SQLAlchemyAsyncConfig(...)` (the whole construction moves to
  `build_alchemy_config`).

CLAUDE.md changes:

- New "Database bootstrap" section under the existing "Commands"
  block, pointing at `just db-init` / `db-revision` / `db-check`
  and ADR-021.
- "Critical layering rule" section grows to list both carve-outs:
  `db/models/_auth/_session.py` (existing) and `db/config.py` (new).
- "ADR pointers" section lists ADR-021.

## ADR-021

Title: *"Database bootstrap via Alembic and the advanced-alchemy CLI."*

Captures:

- Why migrations (vs. `create_all`-from-a-CLI): pre-release discipline,
  long-lived dev DBs survive schema changes, drift detection in CI.
- Why advanced-alchemy CLI (vs. raw `alembic`): we already depend on
  advanced-alchemy; its CLI's `--config <dotted-path>` resolves any
  `SQLAlchemyAsyncConfig` regardless of framework wiring; no
  duplicate Alembic config to maintain.
- Why in-package migrations (vs. repo-root): ships with the wheel,
  co-located with the models that drive them, layering-rule clean.
- Why fail-fast startup gate (vs. trust-the-deployer): catches
  misconfiguration immediately; tests stamp HEAD so the invariant is
  uniform across environments.

Follows the post-ADR-016 template (`docs/adr/_template.md`).

## Final verification (M5.15 / #96)

Run before merging the implementation PR (this docs PR is exempt):

```
just db-init                # apply migrations against a fresh sqlite
just db-check               # no model↔migration drift
uv run pytest               # full test suite
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
just ratchet                # rule baselines hold
cd src/js/web && npm run check
```

Then a live-server smoke test (matches the README's curl example):

```
just bootstrap-dev
uv run litestar --app novamoc.asgi:create_app run --port 8001 &
sleep 2
curl -i -c /tmp/c.txt -X POST http://localhost:8001/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin"}'            # 204 + Set-Cookie
curl -i -b /tmp/c.txt http://localhost:8001/auth/me          # 200
curl -i http://localhost:8001/schema                         # 401
curl -i -b /tmp/c.txt http://localhost:8001/schema           # 200
kill %1
```

Plus a fresh-DB regression check that wasn't previously possible:
delete the SQLite file, start the app without running `db-init`, and
confirm the startup gate fires with the exact `alchemy upgrade head`
remediation message.

The implementation commit ends with `Closes #96.`

## Risks & tradeoffs

- **Module-level `alchemy_config = build_alchemy_config(Settings())`
  runs at import time.** Cheap (one dataclass instantiation, no I/O),
  but means any `import novamoc.db.config` triggers env-var parsing.
  Acceptable: `Settings` already does the same on construction, and
  the dotted-path attribute is the documented advanced-alchemy CLI
  contract.
- **Tests stamp HEAD without running migrations.** A migration that
  diverges from the model definitions (handwritten rename, manual
  ALTER) would pass the test suite via `metadata.create_all` but fail
  the actual `alchemy upgrade head` path. Mitigation: `just db-check`
  in CI catches model↔migration drift; the baseline review process
  catches autogenerate misses.
- **`db/config.py`'s Litestar import.** Already mitigated by the
  documented carve-out, but it's a layering smell. If advanced-alchemy
  ever splits the framework-flavored config from the core one cleanly
  enough that the plugin accepts the core, we revisit.
- **Startup gate latency.** One `SELECT current_rev FROM alembic_version`
  on cold boot. Negligible.
- **Editable installs.** `importlib.resources.files("novamoc.db") /
  "migrations"` should resolve in both editable and wheel modes; we
  verify this in the test suite (one test imports the module and
  asserts the path exists).
