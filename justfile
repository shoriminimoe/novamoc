# List recipes
default:
	just --list --unsorted

# Check everything: `coverage` runs the test suites under coverage so the
# ratchet has fresh inputs. Fast local loop stays `just test`.
check: lint format typecheck coverage ratchet db-check

# Lint everything
[parallel]
lint: lint-py

# Format everything
[parallel]
format: format-py

# Typecheck everything
[parallel]
typecheck: typecheck-py typecheck-js

# Test everything
[parallel]
test: test-py test-js

# Run the backend server
serve: render-problem-docs
	uv run litestar --app novamoc.asgi:create_app run

# Apply all pending migrations against $NOVAMOC_DB_URL.
db-init:
	uv run alchemy --config novamoc.db.config.alchemy_config upgrade head --no-prompt

# Generate a new revision from the current models.
db-revision message:
	uv run alchemy --config novamoc.db.config.alchemy_config make-migrations -m "{{message}}" --autogenerate --no-prompt

# CI gate: fail if models drift from the migration tree.
db-check:
	uv run alchemy --config novamoc.db.config.alchemy_config check

# Apply migrations, then create the dev tenant + admin user.
# Single-transaction bootstrap (#128): re-running after any partial
# failure reuses prior rows instead of accumulating orphan tenants
# or leaving a tenant-less admin behind. Production deployments run
# the same ``novamoc bootstrap-admin`` invocation in an init container.
bootstrap-dev:
	#!/usr/bin/env bash
	set -euo pipefail
	# Production-safety: refuse to bootstrap when NOVAMOC_DB_URL points
	# at a non-SQLite target (likely a misconfigured shell with prod
	# credentials in the env). The guard runs before ``db-init`` (which
	# is invoked from this script body rather than as a ``just``
	# dependency, so the check fires first). Operators who really mean
	# it can opt out via ``NOVAMOC_ALLOW_NON_SQLITE_BOOTSTRAP=1``.
	case "${NOVAMOC_DB_URL:-}" in
		sqlite*|"")
			;;
		*)
			if [ "${NOVAMOC_ALLOW_NON_SQLITE_BOOTSTRAP:-}" != "1" ]; then
				echo "Refusing to bootstrap against non-SQLite URL: $NOVAMOC_DB_URL" >&2
				echo "Set NOVAMOC_ALLOW_NON_SQLITE_BOOTSTRAP=1 to override." >&2
				exit 1
			fi
			;;
	esac
	just db-init
	uv run novamoc bootstrap-admin \
		--tenant-display-name "Development" \
		--username admin \
		--password admin
	echo "Bootstrap complete. Login at /login with admin / admin."

# Build python packages
build-py: render-problem-docs
	uv build

# Render per-code problem-details docs (markdown → HTML, build-time).
# Output lands under docs/problems_html/ with an inner layout that
# mirrors the install path; uv_build's [tool.uv.build-backend.data]
# `purelib` scheme ships it into the wheel as package data.
render-problem-docs:
	uv run python scripts/render_problem_docs.py

# Lint python — auto-fixes what's fixable; the ratchet gates remaining violations
lint-py:
	uv run ruff check --fix --exit-zero --output-format grouped 

# Format python
format-py:
	uv run ruff format

# Typecheck python
typecheck-py:
	uv run ty check

# Typecheck SPA (svelte-check + tsc for vite.config / playwright.config /
# svelte.config); `svelte-kit sync` runs first to generate $app, $lib, and
# $types ambient declarations the typecheck depends on.
typecheck-js:
	cd src/js/web && npm run check

# Test python
test-py:
	uv run pytest

# Test javascript (Vitest component tests). Browser e2e is `test-e2e`,
# kept out of the fast `just test` / `just check` loop because it boots
# the API (migrate + seed) and a real Chromium — see `test-e2e`.
test-js: test-js-unit

# Vitest component tests in jsdom
test-js-unit:
	cd src/js/web && npm run test

# Playwright browser e2e tests (issue #197). Deliberately NOT wired into
# the `test`/`check` composites: it boots the Python API against a
# throwaway file SQLite DB (migrate via db-init + seed via
# bootstrap-admin, per the webServer chain in playwright.config.ts),
# launches Vite, and drives a real Chromium — too heavy for the fast
# inner loop. Run it explicitly, and in its own CI job (`.github/workflows/ci.yml`).
test-e2e:
	cd src/js/web && npm run test:e2e

# Run both test suites under coverage and write artifacts
[parallel]
coverage: coverage-py coverage-js

# Python coverage: writes coverage.xml + htmlcov/ + pytest-junit.xml
coverage-py:
	uv run pytest --cov --cov-branch --cov-report=xml --cov-report=html --cov-report=term --junit-xml=pytest-junit.xml

# JS coverage: writes src/js/web/coverage/ + src/js/web/vitest-junit.xml
coverage-js:
	cd src/js/web && npm run test -- --coverage --reporter=default --reporter=junit --outputFile.junit=./vitest-junit.xml

# Check ruff violation counts against the committed ratchet baseline
ratchet:
	uv run python scripts/ratchet.py

# Update the ratchet baseline from the current ruff state (commit the change)
ratchet-update:
	uv run python scripts/ratchet.py --update

# Clean artifacts
clean:
	rm -rf dist build
