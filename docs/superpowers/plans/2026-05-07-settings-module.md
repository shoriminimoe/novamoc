# Settings module — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-built test `app` fixture and scattered hardcoded knobs (`asgi.py` connection string, `config.problem_docs_base_url()`) with a frozen-dataclass `Settings` aggregate. `create_app(settings: Settings | None = None)` is the single seam; tests pass a literal `Settings(...)` so the app construction is no longer duplicated.

**Architecture:** Frozen `@dataclass(frozen=True, slots=True)` for `DatabaseSettings`, `ServerSettings`, `ProblemSettings`, top-level `Settings` aggregating them. Each field uses `field(default_factory=...)` to read env at construction time. No `from_env` classmethods, no `@lru_cache`, no module-level cache. `_problem_details.py` becomes factory-style (`make_*_converter(base_url)`) so the URL flows in explicitly.

**Tech Stack:** Python 3.14, frozen dataclasses, msgspec, advanced_alchemy, Litestar.

**Spec:** `docs/superpowers/specs/2026-05-07-settings-module-design.md`.

---

## Repo conventions you must know

- Python package root is `src/py/novamoc/`. Imports look like `from novamoc.config import Settings`.
- All commands run via `uv run` (e.g. `uv run pytest`, `uv run ruff check --fix`). Don't activate a venv manually.
- pytest is in asyncio auto mode (see `pyproject.toml [tool.pytest.ini_options]`) — async tests don't need `@pytest.mark.asyncio`.
- The DB layer (`src/py/novamoc/db/`) must NOT import `advanced_alchemy.extensions.litestar`. Web-facing code (asgi, controllers, services) is allowed to. This work touches `config.py`, `api/_problem_details.py`, `asgi.py`, and tests — no db-layer changes required.
- Frozen dataclasses + msgspec Structs are introspected at runtime, so ruff TC001/2/3 won't move their imports under `if TYPE_CHECKING:` (configured in `pyproject.toml [tool.ruff.lint.flake8-type-checking].runtime-evaluated-base-classes`). You don't need to do anything special — just write normal field annotations.
- Run `just check` before committing each task (composite of `lint + format + typecheck + test`). If ruff reports new violations, read the rule (`uv run ruff rule <code>`) and fix the code; don't bump the ratchet.
- If ruff's per-rule counts went *down* during a task (likely with cleanup tasks like 8), run `just ratchet-update` and include the regenerated `.ruff-ratchet.json` in the same commit. The ratchet only goes down — see CLAUDE.md "Linting and the ratchet".
- Single-line comments where useful, no docstrings on trivial helpers, no emojis.
- novaMOC is unreleased — breaking changes are fine. Don't add deprecation aliases for renamed symbols. (See CLAUDE.md "Pre-release status".)

## File map

**Modify:**
- `src/py/novamoc/config.py` — add `_to_bool`, `_str_env`, `_bool_env` helpers and `DatabaseSettings`, `ServerSettings`, `ProblemSettings`, `Settings` dataclasses. Remove `problem_docs_base_url()` at the end. Keep `problem_html_dir()` unchanged.
- `src/py/novamoc/api/_problem_details.py` — `_type_uri` takes `base_url`; the four public converters become factory functions `make_*_converter(base_url) -> Callable[[Exc], ProblemDetailsException]`. Drop the `from novamoc.config import problem_docs_base_url` import.
- `src/py/novamoc/asgi.py` — `create_app(settings: Settings | None = None)`; build alchemy config from settings; conditionally include `GranianPlugin`; wire converter factories with `s.problem.docs_base_url`.
- `tests/conftest.py` — drop the manual Litestar build in the `app` fixture; add a `settings` fixture; `app` calls `create_app(settings=settings)`. Remove the `_problem_docs_base_url` autouse session fixture.
- `tests/test_config.py` — extend with new dataclass tests; delete the two `problem_docs_base_url` tests at the end.
- `tests/api/test_problem_details.py` — update each converter call site to construct the appropriate factory with `base_url="http://test"`.

**Create:** none.

---

## Task 1: Env-reading helpers (`_to_bool`, `_str_env`, `_bool_env`)

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `tests/test_config.py`

These are pure additions. The existing `problem_docs_base_url()` function stays in place for now — it gets removed in Task 8.

- [ ] **Step 1a: Move `import pytest` out of TYPE_CHECKING**

The existing `tests/test_config.py` imports pytest only under `if TYPE_CHECKING:` because the current tests use `pytest.MonkeyPatch` only as an annotation. The new tests use `@pytest.mark.parametrize` and `pytest.raises` at runtime. Edit the imports:

```python
from __future__ import annotations

import pytest

from novamoc.config import problem_docs_base_url
```

Remove the now-empty `if TYPE_CHECKING:` block and the `from typing import TYPE_CHECKING` import.

- [ ] **Step 1b: Append the failing tests for `_to_bool`**

Add at the bottom of `tests/test_config.py` (along with a new import line for the helper):

```python
from novamoc.config import _bool_env, _str_env, _to_bool


class TestToBool:
    def test_none_returns_default_true(self) -> None:
        assert _to_bool(None, default=True) is True

    def test_none_returns_default_false(self) -> None:
        assert _to_bool(None, default=False) is False

    @pytest.mark.parametrize("raw", ["true", "TRUE", "True"])
    def test_truthy_strings(self, raw: str) -> None:
        assert _to_bool(raw, default=False) is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", "False"])
    def test_falsy_strings(self, raw: str) -> None:
        assert _to_bool(raw, default=True) is False

    def test_one_is_true(self) -> None:
        assert _to_bool("1", default=False) is True

    def test_zero_is_false(self) -> None:
        assert _to_bool("0", default=True) is False

    @pytest.mark.parametrize("raw", ["yes", "no", "on", "off", ""])
    def test_garbage_raises(self, raw: str) -> None:
        with pytest.raises(ValueError):
            _to_bool(raw, default=False)
```

The `from novamoc.config import _bool_env, _str_env, _to_bool` line should move up next to the existing `from novamoc.config import problem_docs_base_url` line (ruff will reorder when you run `--fix`).

- [ ] **Step 2: Run the tests — they should fail**

Run: `uv run pytest tests/test_config.py::TestToBool -v`

Expected: ImportError on `_to_bool` (cannot import name).

- [ ] **Step 3: Implement `_to_bool` in `src/py/novamoc/config.py`**

Add near the top of `config.py`, after the existing imports:

```python
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})


def _to_bool(value: str | None, *, default: bool) -> bool:
    """Parse an env-var string as a bool. Return ``default`` when value is None.

    Accepts ``true`` / ``false`` / ``1`` / ``0`` case-insensitively. Any other
    set value raises ``ValueError`` so a typo in the deployment is a startup
    failure, not a silent default.
    """
    if value is None:
        return default
    normalized = value.lower()
    if normalized in _TRUE_LITERALS:
        return True
    if normalized in _FALSE_LITERALS:
        return False
    msg = f"cannot parse {value!r} as bool; expected one of true/false/1/0"
    raise ValueError(msg)
```

- [ ] **Step 4: Verify `_to_bool` tests pass**

Run: `uv run pytest tests/test_config.py::TestToBool -v`

Expected: all tests pass.

- [ ] **Step 5: Write failing tests for `_str_env` and `_bool_env`**

Append to `tests/test_config.py`:

```python
class TestStrEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_STR", raising=False)
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "fallback"

    def test_returns_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_STR", "from-env")
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "from-env"

    def test_factory_re_reads_each_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_STR", raising=False)
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "fallback"
        monkeypatch.setenv("NOVAMOC_X_TEST_STR", "now-set")
        assert factory() == "now-set"


class TestBoolEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_BOOL", raising=False)
        assert _bool_env("NOVAMOC_X_TEST_BOOL", True)() is True
        assert _bool_env("NOVAMOC_X_TEST_BOOL", False)() is False

    def test_parses_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "true")
        assert _bool_env("NOVAMOC_X_TEST_BOOL", False)() is True
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "false")
        assert _bool_env("NOVAMOC_X_TEST_BOOL", True)() is False

    def test_garbage_propagates_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "yes")
        with pytest.raises(ValueError):
            _bool_env("NOVAMOC_X_TEST_BOOL", False)()
```

- [ ] **Step 6: Run the tests — they should fail**

Run: `uv run pytest tests/test_config.py::TestStrEnv tests/test_config.py::TestBoolEnv -v`

Expected: ImportError on `_str_env` / `_bool_env`.

- [ ] **Step 7: Implement `_str_env` and `_bool_env`**

Add to `src/py/novamoc/config.py`, below `_to_bool`:

```python
from collections.abc import Callable


def _str_env(name: str, default: str) -> Callable[[], str]:
    """Return a `default_factory` that reads ``name`` from env at call time."""
    return lambda: os.environ.get(name, default)


def _bool_env(name: str, default: bool) -> Callable[[], bool]:
    """Return a `default_factory` that reads ``name`` from env and parses as bool."""
    return lambda: _to_bool(os.environ.get(name), default=default)
```

(The `Callable` import goes with the existing imports at the top of the file. Keep imports sorted as ruff prefers.)

- [ ] **Step 8: Verify `_str_env` and `_bool_env` tests pass**

Run: `uv run pytest tests/test_config.py -v`

Expected: all tests pass (the new ones plus the two existing `problem_docs_base_url` tests).

- [ ] **Step 9: Run linters and type checker**

Run: `uv run ruff check src/py/novamoc/config.py tests/test_config.py`

Then: `uv run ruff format src/py/novamoc/config.py tests/test_config.py`

Then: `uv run ty check`

Expected: clean. If ruff complains about `S101` (assert in tests), that's already in the project-wide ignore — fine. If ruff complains about a test using `pytest.MonkeyPatch` as an annotation when it's only TYPE_CHECKING-imported, change the import to runtime (move `import pytest` out of `if TYPE_CHECKING:`).

- [ ] **Step 10: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): add _to_bool / _str_env / _bool_env env helpers"
```

---

## Task 2: `DatabaseSettings` dataclass

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from dataclasses import FrozenInstanceError

from novamoc.config import DatabaseSettings


class TestDatabaseSettings:
    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "NOVAMOC_DB_URL",
            "NOVAMOC_DB_STATIC_POOL",
            "NOVAMOC_DB_CREATE_ALL",
            "NOVAMOC_DB_BEFORE_SEND_HANDLER",
        ):
            monkeypatch.delenv(var, raising=False)

        s = DatabaseSettings()
        assert s.url == "sqlite+aiosqlite:///novamoc.sqlite"
        assert s.static_pool is False
        assert s.create_all is True
        assert s.before_send_handler == "autocommit"

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "sqlite+aiosqlite:///custom.sqlite")
        monkeypatch.setenv("NOVAMOC_DB_STATIC_POOL", "true")
        monkeypatch.setenv("NOVAMOC_DB_CREATE_ALL", "false")
        monkeypatch.setenv("NOVAMOC_DB_BEFORE_SEND_HANDLER", "manual")

        s = DatabaseSettings()
        assert s.url == "sqlite+aiosqlite:///custom.sqlite"
        assert s.static_pool is True
        assert s.create_all is False
        assert s.before_send_handler == "manual"

    def test_explicit_kwargs_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "from-env")
        s = DatabaseSettings(url="explicit")
        assert s.url == "explicit"

    def test_partial_construction_re_reads_env_for_unset_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_DB_STATIC_POOL", "true")
        s = DatabaseSettings(url="explicit")
        assert s.url == "explicit"
        assert s.static_pool is True  # came from env

    def test_is_frozen(self) -> None:
        s = DatabaseSettings()
        with pytest.raises(FrozenInstanceError):
            s.url = "different"  # ty: ignore[invalid-assignment]
```

- [ ] **Step 2: Run the tests — they should fail**

Run: `uv run pytest tests/test_config.py::TestDatabaseSettings -v`

Expected: ImportError.

- [ ] **Step 3: Implement `DatabaseSettings`**

Add to `src/py/novamoc/config.py`, below the helpers:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = field(
        default_factory=_str_env(
            "NOVAMOC_DB_URL", "sqlite+aiosqlite:///novamoc.sqlite"
        )
    )
    static_pool: bool = field(
        default_factory=_bool_env("NOVAMOC_DB_STATIC_POOL", False)
    )
    create_all: bool = field(default_factory=_bool_env("NOVAMOC_DB_CREATE_ALL", True))
    before_send_handler: str = field(
        default_factory=_str_env("NOVAMOC_DB_BEFORE_SEND_HANDLER", "autocommit")
    )
```

(Add `from dataclasses import dataclass, field` to the imports at the top of the file, keeping sort order.)

- [ ] **Step 4: Verify the tests pass**

Run: `uv run pytest tests/test_config.py::TestDatabaseSettings -v`

Expected: all 5 tests pass.

- [ ] **Step 5: Lint, format, typecheck**

Run: `uv run ruff check src/py/novamoc/config.py tests/test_config.py && uv run ruff format src/py/novamoc/config.py tests/test_config.py && uv run ty check`

Expected: clean. If ruff RUF012 fires about the frozenset literals being mutable defaults — irrelevant to dataclass fields; the `_TRUE_LITERALS` from Task 1 is at module scope. If `ty` complains about `s.url = "different"` not matching the frozen-dataclass type, the `# ty: ignore[invalid-assignment]` should silence it.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): add DatabaseSettings frozen dataclass"
```

---

## Task 3: `ServerSettings` and `ProblemSettings`

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `tests/test_config.py`

Both classes have a single field; lump them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from novamoc.config import ProblemSettings, ServerSettings


class TestServerSettings:
    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_SERVER_GRANIAN", raising=False)
        assert ServerSettings().granian is True

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_SERVER_GRANIAN", "false")
        assert ServerSettings().granian is False

    def test_explicit_kwarg_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_SERVER_GRANIAN", "true")
        assert ServerSettings(granian=False).granian is False


class TestProblemSettings:
    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", raising=False)
        assert ProblemSettings().docs_base_url == "http://localhost:8000"

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "https://docs.example.com")
        assert ProblemSettings().docs_base_url == "https://docs.example.com"

    def test_explicit_kwarg_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "https://from-env.example")
        assert ProblemSettings(docs_base_url="https://explicit").docs_base_url == "https://explicit"
```

- [ ] **Step 2: Run the tests — they should fail**

Run: `uv run pytest tests/test_config.py::TestServerSettings tests/test_config.py::TestProblemSettings -v`

Expected: ImportError.

- [ ] **Step 3: Implement both dataclasses**

Add to `src/py/novamoc/config.py`, below `DatabaseSettings`:

```python
@dataclass(frozen=True, slots=True)
class ServerSettings:
    granian: bool = field(default_factory=_bool_env("NOVAMOC_SERVER_GRANIAN", True))


@dataclass(frozen=True, slots=True)
class ProblemSettings:
    docs_base_url: str = field(
        default_factory=_str_env(
            "NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://localhost:8000"
        )
    )
```

- [ ] **Step 4: Verify the tests pass**

Run: `uv run pytest tests/test_config.py -v`

Expected: all tests pass (existing two `problem_docs_base_url` tests still pass; both new test classes pass).

- [ ] **Step 5: Lint, format, typecheck**

Run: `uv run ruff check && uv run ruff format && uv run ty check`

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): add ServerSettings and ProblemSettings"
```

---

## Task 4: `Settings` aggregator

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from novamoc.config import Settings


class TestSettings:
    def test_default_construction_uses_env_aware_children(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "sqlite+aiosqlite:///x.sqlite")
        monkeypatch.setenv("NOVAMOC_SERVER_GRANIAN", "false")
        monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "https://x")

        s = Settings()
        assert s.db.url == "sqlite+aiosqlite:///x.sqlite"
        assert s.server.granian is False
        assert s.problem.docs_base_url == "https://x"

    def test_explicit_child_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "from-env")
        s = Settings(db=DatabaseSettings(url="explicit"))
        assert s.db.url == "explicit"

    def test_is_frozen(self) -> None:
        s = Settings()
        with pytest.raises(FrozenInstanceError):
            s.db = DatabaseSettings()  # ty: ignore[invalid-assignment]
```

- [ ] **Step 2: Run the tests — they should fail**

Run: `uv run pytest tests/test_config.py::TestSettings -v`

Expected: ImportError.

- [ ] **Step 3: Implement `Settings`**

Add to `src/py/novamoc/config.py`, below `ProblemSettings`:

```python
@dataclass(frozen=True, slots=True)
class Settings:
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    problem: ProblemSettings = field(default_factory=ProblemSettings)
```

- [ ] **Step 4: Verify the tests pass**

Run: `uv run pytest tests/test_config.py -v`

Expected: all tests pass.

- [ ] **Step 5: Lint, format, typecheck, full test suite**

Run: `just check`

Expected: green. If anything fails in tests outside `test_config.py`, that's a regression — investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "feat(config): add Settings aggregator dataclass"
```

---

## Task 5: Migrate `_problem_details.py` to factory pattern

**Files:**
- Modify: `src/py/novamoc/api/_problem_details.py`
- Modify: `src/py/novamoc/asgi.py`
- Modify: `tests/conftest.py`
- Modify: `tests/api/test_problem_details.py`

This is the only task that touches multiple modules in one commit. The reason: the four converters' signatures change, and every caller must update at the same time or the codebase won't compile. Production still reads the URL via the existing `problem_docs_base_url()` helper — that helper goes away in Task 8.

- [ ] **Step 1: Update the test file with the new factory call shape (failing)**

Edit `tests/api/test_problem_details.py`. Change the import block:

```python
from novamoc.api._problem_details import (
    ProblemDetails,
    make_litestar_validation_error_converter,
    make_msgspec_validation_error_converter,
    make_schema_error_converter,
)
```

Change each test that builds a converter. Replace direct calls like `schema_error_to_problem_details(exc)` with the factory pattern. Full new file:

```python
from __future__ import annotations

import msgspec
from litestar.exceptions import ValidationException
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.api._problem_details import (
    ProblemDetails,
    make_litestar_validation_error_converter,
    make_msgspec_validation_error_converter,
    make_schema_error_converter,
)
from novamoc.domain.schema._errors import (
    ConflictError,
    EntityNotFoundError,
    ErrorCode,
    PayloadShapeError,
)

_BASE_URL = "http://test"


def test_problem_details_minimal_encode() -> None:
    pd = ProblemDetails(
        type="http://test/problems/name_reserved.html",
        title="Name reserved",
        status=409,
        detail="Name is already in use by another entity.",
        instance="urn:uuid:01JABC...",
    )
    encoded = msgspec.json.decode(msgspec.json.encode(pd))
    assert encoded == {
        "type": "http://test/problems/name_reserved.html",
        "title": "Name reserved",
        "status": 409,
        "detail": "Name is already in use by another entity.",
        "instance": "urn:uuid:01JABC...",
    }


def test_schema_command_error_conflict_renders_409_with_extras() -> None:
    convert = make_schema_error_converter(_BASE_URL)
    exc = ConflictError(code=ErrorCode.NAME_RESERVED, name="Truck")
    pd_exc = convert(exc)

    assert isinstance(pd_exc, ProblemDetailsException)
    assert pd_exc.status_code == 409
    assert pd_exc.type_ == "http://test/problems/name_reserved.html"
    assert pd_exc.title == "Name reserved"
    assert pd_exc.detail == "Name is already in use by another entity."
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")
    assert pd_exc.extra == {"name": "Truck"}


def test_schema_command_error_payload_shape_renders_400() -> None:
    convert = make_schema_error_converter(_BASE_URL)
    exc = PayloadShapeError(code=ErrorCode.PAYLOAD_NO_CHANGES)
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/payload_no_changes.html"


def test_schema_command_error_entity_not_found_renders_404() -> None:
    convert = make_schema_error_converter(_BASE_URL)
    exc = EntityNotFoundError(code=ErrorCode.ENTITY_NOT_FOUND)
    pd_exc = convert(exc)

    assert pd_exc.status_code == 404
    assert pd_exc.type_ == "http://test/problems/entity_not_found.html"


def test_msgspec_validation_error_renders_400_invalid_payload_shape() -> None:
    convert = make_msgspec_validation_error_converter(_BASE_URL)
    exc = msgspec.ValidationError("expected str, got int")
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/invalid_payload_shape.html"
    assert pd_exc.title == "Invalid payload shape"
    assert "expected str, got int" in pd_exc.detail
    assert pd_exc.instance is not None
    assert pd_exc.instance.startswith("urn:uuid:")


def test_litestar_validation_exception_renders_400_invalid_payload_shape() -> None:
    convert = make_litestar_validation_error_converter(_BASE_URL)
    exc = ValidationException(detail="malformed body")
    pd_exc = convert(exc)

    assert pd_exc.status_code == 400
    assert pd_exc.type_ == "http://test/problems/invalid_payload_shape.html"
    assert pd_exc.title == "Invalid payload shape"
    assert pd_exc.detail == "malformed body"


def test_tenant_resolution_error_renders_401() -> None:
    from novamoc.api._problem_details import (
        make_tenant_resolution_error_converter,
    )
    from novamoc.domain.accounts import TenantResolutionError

    convert = make_tenant_resolution_error_converter(_BASE_URL)
    exc = TenantResolutionError()
    pd_exc = convert(exc)

    assert pd_exc.status_code == 401
    assert pd_exc.type_ == "http://test/problems/tenant_not_resolved.html"
    assert pd_exc.title == "Tenant not resolved"
    assert pd_exc.extra is None
```

- [ ] **Step 2: Run the tests — they should fail**

Run: `uv run pytest tests/api/test_problem_details.py -v`

Expected: ImportError on `make_*_converter` symbols.

- [ ] **Step 3: Refactor `_problem_details.py`**

Replace `src/py/novamoc/api/_problem_details.py` (full file):

```python
"""RFC 9457 problem-details rendering for the whole API.

The `ProblemDetails` msgspec struct is published as the OpenAPI response
body for every error path. The converters below turn typed exceptions
(`SchemaError`, msgspec/Litestar validation errors, eventually
others) into Litestar's `ProblemDetailsException`, which the
`ProblemDetailsPlugin` renders as `application/problem+json`.

Wire shape:
- `type` — opaque URI; clients branch on its leaf segment (the code).
- `title` — short, fixed string per code.
- `status` — HTTP status code, also on the response line.
- `detail` — human-readable message; not stable, do not branch on it.
- `instance` — `urn:uuid:<uuid4>` per occurrence, for log correlation.

Per-error-code extras (e.g., the conflicting `name`) are RFC 9457 §3.2
extension members — top-level keys alongside the standard slots.

Each converter is built by a `make_*_converter(base_url)` factory that
closes over the configured docs base URL. ``create_app`` constructs
them once at startup with ``Settings.problem.docs_base_url`` and
registers them on the `ProblemDetailsPlugin`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

import msgspec
from litestar.plugins.problem_details import ProblemDetailsException

from novamoc.domain.schema._errors import (
    ErrorCode,
    SchemaError,
)

if TYPE_CHECKING:
    from litestar.exceptions import ValidationException

    from novamoc.domain.accounts import TenantResolutionError

_TITLES: dict[ErrorCode, str] = {
    ErrorCode.PAYLOAD_NO_CHANGES: "Payload contained no changes",
    ErrorCode.INVALID_PAYLOAD_SHAPE: "Invalid payload shape",
    ErrorCode.NAME_RESERVED: "Name reserved",
    ErrorCode.PARENT_TYPE_NOT_FOUND: "Parent type not found",
    ErrorCode.ENTITY_NOT_FOUND: "Entity not found",
}


_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.PAYLOAD_NO_CHANGES: 400,
    ErrorCode.INVALID_PAYLOAD_SHAPE: 400,
    ErrorCode.NAME_RESERVED: 409,
    ErrorCode.PARENT_TYPE_NOT_FOUND: 409,
    ErrorCode.ENTITY_NOT_FOUND: 404,
}


def _type_uri(code: ErrorCode | str, base_url: str) -> str:
    # The ``.html`` suffix is part of the URL path, not the code; clients
    # that branch on the leaf segment strip the extension to recover the
    # code. See ADR-018.
    code_str = code.value if isinstance(code, ErrorCode) else code
    return f"{base_url}/problems/{code_str}.html"


class ProblemDetails(msgspec.Struct, omit_defaults=True):
    """OpenAPI body schema for an `application/problem+json` response.

    Documentation-only: this struct is never instantiated at runtime.
    It exists so controllers can reference it from `ResponseSpec(...)`
    and clients generated from the OpenAPI document see typed fields
    (`type`, `title`, `status`, `detail`, `instance`) instead of the
    generic shape Litestar would otherwise emit for
    `ProblemDetailsException`. Per-error extension members (RFC 9457
    §3.2) are not declared here — they ride through `ProblemDetailsException.extra`
    at runtime and consumers ignore unknown fields.
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str


def make_instance() -> str:
    """Return an opaque per-occurrence instance identifier (`urn:uuid:<uuid4>`)."""

    return f"urn:uuid:{uuid.uuid4()}"


def make_schema_error_converter(
    base_url: str,
) -> Callable[[SchemaError], ProblemDetailsException]:
    def _convert(exc: SchemaError) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri(exc.code, base_url),
            title=_TITLES[exc.code],
            status_code=_STATUS_CODES[exc.code],
            detail=exc.message,
            instance=make_instance(),
            extra=dict(exc.extras) if exc.extras else None,
        )

    return _convert


def make_tenant_resolution_error_converter(
    base_url: str,
) -> Callable[[TenantResolutionError], ProblemDetailsException]:
    def _convert(exc: TenantResolutionError) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri("tenant_not_resolved", base_url),
            title="Tenant not resolved",
            status_code=401,
            detail=exc.detail,
            instance=make_instance(),
        )

    return _convert


def _make_invalid_payload_shape(base_url: str) -> Callable[[str], ProblemDetailsException]:
    code = ErrorCode.INVALID_PAYLOAD_SHAPE

    def _build(detail: str) -> ProblemDetailsException:
        return ProblemDetailsException(
            type_=_type_uri(code, base_url),
            title=_TITLES[code],
            status_code=_STATUS_CODES[code],
            detail=detail,
            instance=make_instance(),
        )

    return _build


def make_msgspec_validation_error_converter(
    base_url: str,
) -> Callable[[msgspec.ValidationError], ProblemDetailsException]:
    build = _make_invalid_payload_shape(base_url)

    def _convert(exc: msgspec.ValidationError) -> ProblemDetailsException:
        return build(str(exc))

    return _convert


def make_litestar_validation_error_converter(
    base_url: str,
) -> Callable[[ValidationException], ProblemDetailsException]:
    build = _make_invalid_payload_shape(base_url)

    def _convert(exc: ValidationException) -> ProblemDetailsException:
        return build(exc.detail or str(exc))

    return _convert
```

Note: `ValidationException` and `TenantResolutionError` are still TYPE_CHECKING-only imports because they appear only in annotations (the closures' parameter types). Runtime evaluation isn't needed.

- [ ] **Step 4: Update `src/py/novamoc/asgi.py` to use the factories**

Edit `src/py/novamoc/asgi.py`. Replace the import:

```python
    from novamoc.api._problem_details import (
        litestar_validation_error_to_problem_details,
        msgspec_validation_error_to_problem_details,
        schema_error_to_problem_details,
        tenant_resolution_error_to_problem_details,
    )
```

with:

```python
    from novamoc.api._problem_details import (
        make_litestar_validation_error_converter,
        make_msgspec_validation_error_converter,
        make_schema_error_converter,
        make_tenant_resolution_error_converter,
    )
    from novamoc.config import problem_docs_base_url
```

Then replace the `exception_to_problem_detail_map=...` block with:

```python
    base_url = problem_docs_base_url()
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: make_schema_error_converter(base_url),
            TenantResolutionError: make_tenant_resolution_error_converter(base_url),
            msgspec.ValidationError: make_msgspec_validation_error_converter(base_url),
            ValidationException: make_litestar_validation_error_converter(base_url),
        },
    )
```

- [ ] **Step 5: Update `tests/conftest.py` to use the factories**

In `tests/conftest.py`, update the import:

```python
from novamoc.api._problem_details import (
    make_litestar_validation_error_converter,
    make_msgspec_validation_error_converter,
    make_schema_error_converter,
    make_tenant_resolution_error_converter,
)
```

Replace the existing `from novamoc.api._problem_details import (litestar_validation_error_to_problem_details, msgspec_validation_error_to_problem_details, schema_error_to_problem_details, tenant_resolution_error_to_problem_details,)` block.

In the `app` fixture body, replace the `exception_to_problem_detail_map=...` block with:

```python
    base_url = "http://test"
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: make_schema_error_converter(base_url),
            TenantResolutionError: make_tenant_resolution_error_converter(base_url),
            msgspec.ValidationError: make_msgspec_validation_error_converter(base_url),
            ValidationException: make_litestar_validation_error_converter(base_url),
        },
    )
```

(`"http://test"` is what the `_problem_docs_base_url` autouse fixture has been pinning the env to. Hardcoding it here is temporary; Task 7 swaps the whole `app` fixture to call `create_app(settings=...)` and the URL flows from the `settings` fixture instead.)

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest -v`

Expected: all tests pass. The `test_problem_details.py` tests now exercise the factories directly. End-to-end tests in `tests/schema/test_endpoint_e2e.py` still get the same `http://test/problems/...` URIs because `app` fixture wires the converters with that base.

- [ ] **Step 7: Lint, format, typecheck**

Run: `just check`

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/py/novamoc/api/_problem_details.py src/py/novamoc/asgi.py tests/conftest.py tests/api/test_problem_details.py
git commit -m "refactor(problem-details): convert converters to make_*_converter factories"
```

---

## Task 6: `create_app(settings: Settings | None = None)` in `asgi.py`

**Files:**
- Modify: `src/py/novamoc/asgi.py`

This task changes only `asgi.py`. The test `app` fixture still builds a Litestar by hand — Task 7 deals with that. After this task, calling `create_app()` (no args) reads `Settings()` which reads env, including the test-configured `NOVAMOC_PROBLEM_DOCS_BASE_URL` and `test.sqlite` → `novamoc.sqlite` (the new default).

- [ ] **Step 1: Replace `src/py/novamoc/asgi.py` (full file)**

```python
# Imports inside ``create_app`` are deliberately deferred to keep CLI /
# import-time work cheap; ``create_app`` is only called when actually serving.
# ruff: noqa: PLC0415
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar

    from novamoc.config import Settings


def create_app(settings: Settings | None = None) -> Litestar:
    """Create the ASGI app."""

    import msgspec
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        EngineConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.exceptions import ValidationException
    from litestar.middleware.base import DefineMiddleware
    from litestar.openapi.config import OpenAPIConfig
    from litestar.plugins.problem_details import (
        ProblemDetailsConfig,
        ProblemDetailsPlugin,
    )
    from litestar.static_files import create_static_files_router
    from litestar_granian import GranianPlugin
    from sqlalchemy.pool import StaticPool

    # Register tenant-scoping event handlers on SQLAlchemy.
    import novamoc.db._listeners  # noqa: F401
    from novamoc.api._problem_details import (
        make_litestar_validation_error_converter,
        make_msgspec_validation_error_converter,
        make_schema_error_converter,
        make_tenant_resolution_error_converter,
    )
    from novamoc.config import Settings, problem_html_dir
    from novamoc.domain.accounts import (
        AuthenticationMiddleware,
        TenantContextMiddleware,
        TenantResolutionError,
    )
    from novamoc.domain.schema._errors import SchemaError
    from novamoc.domain.schema.controllers import SchemaController

    s = settings if settings is not None else Settings()

    engine_config = (
        EngineConfig(poolclass=StaticPool) if s.db.static_pool else EngineConfig()
    )
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string=s.db.url,
        before_send_handler=s.db.before_send_handler,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=s.db.create_all,
        engine_config=engine_config,
    )

    base_url = s.problem.docs_base_url
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: make_schema_error_converter(base_url),
            TenantResolutionError: make_tenant_resolution_error_converter(base_url),
            msgspec.ValidationError: make_msgspec_validation_error_converter(base_url),
            ValidationException: make_litestar_validation_error_converter(base_url),
        },
    )

    problem_docs_router = create_static_files_router(
        path="/problems",
        directories=[str(problem_html_dir())],
        name="problems",
    )

    plugins = [
        *([GranianPlugin()] if s.server.granian else []),
        SQLAlchemyPlugin(config=alchemy_config),
        ProblemDetailsPlugin(config=problem_details_config),
    ]

    return Litestar(
        route_handlers=[SchemaController, problem_docs_router],
        middleware=[
            DefineMiddleware(
                AuthenticationMiddleware,
                exclude=r"^/(openapi|problems)",
            ),
            TenantContextMiddleware(),
        ],
        plugins=plugins,
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

Note: the `from novamoc.config import problem_docs_base_url` import added in Task 5 is gone — `s.problem.docs_base_url` replaces it. The `problem_html_dir()` import stays.

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`

Expected: all tests pass. The conftest still has its hand-built Litestar; `create_app` is now a separate code path that the production CLI exercises.

- [ ] **Step 3: Smoke-test that imports resolve**

Run:

```sh
uv run python -c "from novamoc.asgi import create_app; from novamoc.config import Settings; print('imports OK')"
```

Expected: prints `imports OK`. Catches syntax errors, missing imports, and circular-import regressions before Task 7's pytest run does.

(Construction is exercised end-to-end in Task 7 once conftest's `app` fixture starts calling `create_app(settings=...)`. No need to actually call `create_app()` here — that would write `novamoc.sqlite` to the worktree root since `create_all=True`.)

- [ ] **Step 4: Lint, format, typecheck**

Run: `just check`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/py/novamoc/asgi.py
git commit -m "refactor(asgi): create_app takes optional Settings; defaults to Settings()"
```

---

## Task 7: Replace `tests/conftest.py::app` with `create_app(settings=...)`

**Files:**
- Modify: `tests/conftest.py`

This is the deduplication payoff. The `app` fixture's hand-built Litestar goes away.

- [ ] **Step 1: Add the `settings` fixture and rewrite `app`**

In `tests/conftest.py`:

(a) Update the imports — drop the now-unused ones, add `Settings`:

```python
from novamoc.config import (
    DatabaseSettings,
    ProblemSettings,
    ServerSettings,
    Settings,
    problem_html_dir,
)
```

Drop these imports (no longer needed in conftest):

```python
from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar import Litestar
from litestar.exceptions import ValidationException
from litestar.middleware.base import DefineMiddleware
from litestar.openapi.config import OpenAPIConfig
from litestar.plugins.problem_details import (
    ProblemDetailsConfig,
    ProblemDetailsPlugin,
)
from litestar.static_files import create_static_files_router
from sqlalchemy.pool import StaticPool

from novamoc.api._problem_details import (
    make_litestar_validation_error_converter,
    make_msgspec_validation_error_converter,
    make_schema_error_converter,
    make_tenant_resolution_error_converter,
)
from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.domain.accounts import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
    TenantResolutionError,
)
from novamoc.domain.schema._errors import SchemaError
from novamoc.domain.schema.controllers import SchemaController
```

…**except** `PROBLEM_CODES` — that's still used by `_render_problem_html`. Keep it. Same with `Litestar` (still used in fixture annotations) and `problem_html_dir` (used in `_render_problem_html`). Trim only the ones that became unused.

After cleanup, the dedicated novamoc imports near the top should look approximately:

```python
import novamoc.db._listeners  # registers tenant-scoping event handlers
import novamoc.db.models  # noqa: F401 — registers ORM tables on metadata
from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.config import (
    DatabaseSettings,
    ProblemSettings,
    ServerSettings,
    Settings,
    problem_html_dir,
)
from novamoc.db._tenant_context import use_tenant
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)
```

(Use `uv run ruff check --fix tests/conftest.py` after editing — it will reorder and remove unused imports automatically.)

(b) Replace the `app` fixture body. Remove the existing fixture (the hand-built Litestar) and replace with:

```python
@pytest.fixture
def settings() -> Settings:
    """Test-flavoured Settings: in-memory SQLite + StaticPool, no Granian, ``http://test`` docs URL.

    All `DatabaseSettings` fields are passed explicitly so the fixture is
    hermetic against any env vars the developer's shell happens to export.
    """
    return Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:///:memory:",
            static_pool=True,
            create_all=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        problem=ProblemSettings(docs_base_url="http://test"),
    )


@pytest.fixture
async def app(settings: Settings) -> Litestar:
    """A Litestar app for e2e tests, built from the test ``settings`` fixture."""
    from novamoc.asgi import create_app

    return create_app(settings=settings)
```

(c) Remove the `_problem_docs_base_url` autouse session fixture entirely (the whole `def _problem_docs_base_url(...)` block). It's superseded by the `problem.docs_base_url` field on the `settings` fixture.

(d) The `monkeypatch_session` fixture is still used by `_render_problem_html`? Check `_render_problem_html` body — it doesn't take `monkeypatch_session`, only `_default_src_dir` etc. So `monkeypatch_session` can be deleted too if no other fixture takes it. Verify with `grep monkeypatch_session tests/conftest.py` — if the only producer-consumer pair is `monkeypatch_session` ↔ `_problem_docs_base_url`, both go.

(e) Keep the `_render_problem_html` autouse session fixture and the `tenant`, `engine`, `session`, `services`, `seed`, `client` fixtures unchanged.

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`

Expected: all tests pass. The e2e tests now route through `create_app(settings=...)`.

If a test fails because the type URI no longer matches `http://test/...` — investigate; the `settings` fixture sets `problem.docs_base_url="http://test"` which should match what the old `_problem_docs_base_url` autouse pinned via env.

- [ ] **Step 3: Lint, format, typecheck**

Run: `just check`

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): app fixture uses create_app(settings=...) — deduplicates Litestar build"
```

---

## Task 8: Remove `problem_docs_base_url()` and its tests

**Files:**
- Modify: `src/py/novamoc/config.py`
- Modify: `tests/test_config.py`

After Tasks 5-7, no caller imports `problem_docs_base_url` anywhere — verify with `rg "problem_docs_base_url"` before deleting (the only hits should be in `config.py` itself and the two tests).

- [ ] **Step 1: Verify no remaining callers**

Run: `rg "problem_docs_base_url" src/ tests/`

Expected: hits only in `src/py/novamoc/config.py` (the function definition) and `tests/test_config.py` (the two old tests). If any production module still imports it, return to Task 5/6/7 and fix the caller.

- [ ] **Step 2: Delete the function from `config.py`**

In `src/py/novamoc/config.py`, remove:

- The `_PROBLEM_DOCS_BASE_URL_ENV` and `_PROBLEM_DOCS_BASE_URL_DEFAULT` module constants.
- The `def problem_docs_base_url() -> str:` function.

Keep `problem_html_dir()` and everything else (the helpers and dataclasses added in Tasks 1-4).

- [ ] **Step 3: Delete the two superseded tests in `tests/test_config.py`**

Remove `test_problem_docs_base_url_defaults_to_localhost` and `test_problem_docs_base_url_reads_env_var`. Their behaviour is now covered by `TestProblemSettings::test_default_when_env_unset` and `TestProblemSettings::test_reads_env`.

Also remove the `from novamoc.config import problem_docs_base_url` import at the top of the test file.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -v`

Expected: green.

- [ ] **Step 5: Lint, format, typecheck**

Run: `just check`

Expected: green. If ruff complains about an unused `os` import in `config.py`, that means `_str_env` / `_bool_env` aren't using `os.environ.get` — they should be. Investigate.

- [ ] **Step 6: Commit**

```bash
git add src/py/novamoc/config.py tests/test_config.py
git commit -m "refactor(config): drop problem_docs_base_url() — superseded by ProblemSettings"
```

---

## Final verification

- [ ] **Run the full check suite**

Run: `just check`

Expected: lint, format, typecheck, and tests all green.

- [ ] **Smoke-test the import path**

Run: `uv run python -c "from novamoc.asgi import create_app; from novamoc.config import Settings; print('imports OK')"`

Expected: prints `imports OK`.

- [ ] **Confirm the conftest is meaningfully shorter**

Run: `wc -l tests/conftest.py`

Expected: substantially smaller than before (the manual Litestar build was ~50 lines plus its imports). If the line count didn't drop appreciably, double-check Task 7 actually removed the old fixture body.

- [ ] **Confirm `problem_docs_base_url` is gone**

Run: `rg "problem_docs_base_url" src/ tests/`

Expected: no matches.

---

## Migration ordering and atomicity

For the curious — why this ordering, and what's atomic versus serial:

- **Tasks 1-4** add new symbols only. The codebase compiles and tests pass after each.
- **Task 5** is the only multi-file atomic step. The four converter signatures change at once across `_problem_details.py`, `asgi.py`, `tests/conftest.py`, and `tests/api/test_problem_details.py`. Splitting it would require a transitional shim (e.g. keeping the old free functions alongside the factories) and the project's pre-release status (CLAUDE.md → "breaking changes are fine") makes that pointless.
- **Task 6** changes `create_app`'s signature but not what it builds — production behaviour is unchanged because `Settings()` reads the same env vars `problem_docs_base_url()` did. Tests still pass because the conftest still builds its own Litestar.
- **Task 7** is the actual deduplication: conftest's `app` fixture now calls `create_app(settings=...)`. The `_problem_docs_base_url` autouse fixture goes away in the same commit because the test settings supply the URL directly.
- **Task 8** is cleanup: the dead `problem_docs_base_url()` function and its tests are removed once nothing imports them.
