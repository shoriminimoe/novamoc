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
# Idempotent: re-running after the first invocation prints
# "already exists; nothing to do." and exits cleanly. Production
# deployments run the equivalent CLI commands in an init container.
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
	# ``novamoc user exists`` has a three-way exit contract: 0 = exists,
	# 1 = absent, 2 = CLI error (bad NOVAMOC_DB_URL, locked file, ...).
	# Honor all three so a real error doesn't silently become a "user
	# absent, seed now" decision that creates a partial-state DB.
	rc=0
	uv run novamoc user exists admin >/dev/null 2>&1 || rc=$?
	case "$rc" in
		0) echo "admin user already exists; nothing to do."; exit 0 ;;
		1) ;;  # absent → fall through to seeding below
		*) echo "novamoc user exists failed (exit $rc); aborting." >&2; exit "$rc" ;;
	esac
	# Anchor to ``Created tenant <uuid>.`` so future stdout (logging,
	# deprecation notices) doesn't bleed into the parsed UUID. ``exit``
	# stops awk after the first match for the same reason.
	tenant_id=$(uv run novamoc tenant create --display-name "Development" \
	            | awk '/^Created tenant /{print $3; exit}' | tr -d '.')
	echo "Created tenant $tenant_id."
	uv run novamoc user create admin --password admin
	uv run novamoc user add-to-tenant admin "$tenant_id"
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

# Test javascript (Vitest component tests + Playwright browser e2e)
test-js: test-js-unit test-js-e2e

# Vitest component tests in jsdom
test-js-unit:
	cd src/js/web && npm run test

# Playwright browser e2e tests
test-js-e2e:
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
