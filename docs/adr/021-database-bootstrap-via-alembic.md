---
status: "accepted"
date: 2026-05-26
category: storage
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-021: Database bootstrap via Alembic and the advanced-alchemy CLI

## Context and Problem Statement

Until now, `asgi.create_app` built `SQLAlchemyAsyncConfig` inline with `create_all=True`, so the Litestar plugin's lifespan was what created tables on startup. The implicit contract was "boot the app, get tables." That works while every consumer (dev, tests, prod) starts from a fresh empty database, but it conflates two responsibilities — schema management and request serving — into one process, and it offers no way to evolve the schema once a long-lived database exists. How should novaMOC bootstrap and evolve its database schema?

## Decision Drivers

* Pre-release schema churn is high; we need a way to express schema changes that survives across deploys.
* Tests want a fast, hermetic in-memory database — running real migrations per test is too slow.
* The wheel-installed deployment artifact must carry whatever schema is required to bring a fresh DB up.
* Drift between models and schema state should fail loudly, ideally in the same gate as ruff / ty.

## Considered Options

* **Alembic via the advanced-alchemy CLI** (chosen).
* Plain `metadata.create_all` driven by a new `novamoc db init` CLI command — no migrations.
* Hybrid: scaffold the Alembic tree now but defer authoring migrations until first stable release.

## Decision Outcome

Chosen option: **Alembic via the advanced-alchemy CLI**, because it provides migration discipline starting at day one (long-lived dev databases survive schema changes), gives us a model↔schema drift check that fits naturally into CI, and reuses the CLI surface advanced-alchemy already ships (`alchemy upgrade`, `alchemy make-migrations`, `alchemy check`, ...). The migration tree lives at `src/py/novamoc/db/migrations/`, shipped inside the wheel via uv_build's module-root, so wheel-installed deployments find the script tree at the same package path the running code uses. A fail-fast startup gate (`db/_startup.assert_alembic_at_head`) reads the DB's current revision on `on_startup` and refuses to serve when it doesn't match the script tree's HEAD; the error message names the exact `just db-init` recipe to run.

### Consequences

* Good, because contributor / CI / production paths all converge on a single `alchemy upgrade head` command — no environment-conditional code in the server.
* Good, because `just db-check` catches model↔migration drift at the same gate that catches ruff violations.
* Bad, because pre-release schema churn means many small migrations land before any consumer is using them. The user can squash to a fresh baseline closer to first stable release; until then we live with the file count.

### Confirmation

* `just db-check` (and so `just check`) gates model↔migration drift in local pre-commit and CI.
* The startup gate (`db/_startup.assert_alembic_at_head`) catches a misconfigured deployment at process boot.
* The test conftest's stamp-HEAD step makes the gate uniform across tests and prod — there is no test-only escape hatch.

## Pros and Cons of the Options

### Alembic via the advanced-alchemy CLI

* Good, because the CLI is already shipped with our dependency tree; no second migration tool to maintain.
* Good, because `--config <dotted-path>` resolves any `SQLAlchemyAsyncConfig` regardless of framework wiring, so we don't duplicate Alembic config to keep the plugin and the CLI in sync.
* Neutral, because the `db/config.py` module that exposes the dotted-path target imports the Litestar-flavored `SQLAlchemyAsyncConfig` — a second documented carve-out to the "db/ must not depend on Litestar" rule.

### Plain `metadata.create_all` from a CLI

* Good, because cheapest to adopt and works fine while the schema is churning.
* Bad, because any model change against an existing long-lived DB means dropping and re-initializing. Acceptable pre-release per CLAUDE.md, but the work to introduce migrations later is the same work we'd do now.
* Bad, because there is no drift gate — the only signal that schema and models disagree is a runtime SQL error.

### Hybrid (scaffold Alembic, defer authoring)

* Good, because the wiring is in place when migrations are wanted later.
* Bad, because the bootstrap-on-start contract is meaningless without a HEAD to upgrade to — we'd still need a separate `metadata.create_all` path for "no migrations yet," and the dual-mode adds carrying cost.
