# List recipes
default:
	just --list --unsorted

# Check everything: `coverage` runs the test suites under coverage so the
# ratchet has fresh inputs. Fast local loop stays `just test`.
check: lint format typecheck coverage ratchet

# Lint everything
[parallel]
lint: lint-py

# Format everything
[parallel]
format: format-py

# Typecheck everything
[parallel]
typecheck: typecheck-py

# Test everything
[parallel]
test: test-py test-js

# Run the backend server
serve: render-problem-docs
	uv run litestar --app novamoc.asgi:create_app run

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
