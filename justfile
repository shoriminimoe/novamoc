# List recipes
default:
	just --list --unsorted

# Check everything
check: lint format typecheck test

# Lint everything
lint: lint-py

# Format everything
format: format-py

# Typecheck everything
typecheck: typecheck-py

# Test everything
test: test-py

# Run the backend server
serve:
	uv run litestar --app novamoc.asgi:create_app run

# Build python packages
build-py:
	uv build

# Lint python
lint-py:
	uv run ruff check --fix

# Format python
format-py:
	uv run ruff format

# Typecheck python
typecheck-py:
	uv run ty check

# Test python
test-py:
	uv run pytest

# Clean artifacts
clean:
	rm -r dist
