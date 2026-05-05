# List recipes
default:
	just --list --unsorted

# Check everything
check: lint format typecheck test ratchet

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
test: test-py

# Run the backend server
serve:
	uv run litestar --app novamoc.asgi:create_app run

# Build python packages
build-py:
	uv build

# Lint python — auto-fixes what's fixable; the ratchet gates remaining violations
lint-py:
	uv run ruff check --fix --exit-zero

# Format python
format-py:
	uv run ruff format

# Typecheck python
typecheck-py:
	uv run ty check

# Test python
test-py:
	uv run pytest

# Check ruff violation counts against the committed ratchet baseline
ratchet:
	uv run python scripts/ratchet.py

# Update the ratchet baseline from the current ruff state (commit the change)
ratchet-update:
	uv run python scripts/ratchet.py --update

# Clean artifacts
clean:
	rm -r dist
