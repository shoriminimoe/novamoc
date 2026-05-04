build:
	uv build

serve:
	uv run litestar --app novamoc.asgi:create_app run

lint-py:
	uv run ruff check --fix

format-py:
	uv run ruff format

typecheck-py:
	uv run ty check

test-py:
	uv run pytest

check: lint-py format-py typecheck-py

test: test-py

clean:
	rm -r dist
