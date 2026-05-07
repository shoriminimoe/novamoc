# Settings module

## Problem

Three observable symptoms point at the same root cause — runtime knobs don't have a home:

1. **`tests/conftest.py::app` is a near-duplicate of `asgi.py::create_app`.** Both build a Litestar with the same plugins, middleware, and routes; they differ only in the SQLAlchemy connection string, the use of `StaticPool`, the absence of `GranianPlugin` in tests, and (currently) deferred-vs-eager imports. The whole-app reconstruction is what makes any future plugin or middleware a two-place edit.
2. **Hardcoded values are spread across two modules.** `asgi.py` owns the production database URL; `config.py` owns the problem-docs base URL. Each was added when its consumer was added; no one place holds "the runtime knobs." (`domain/accounts/_resolver.py::_TENANT_T1_DEV_TOKEN` is a related leftover but stays a module constant — see Non-goals.)
3. **The single existing env-var helper (`config.problem_docs_base_url()`) re-reads `os.environ` on every call.** That works for one knob but generalises poorly: every future call site repeats the lookup, defaults are easy to drift, and there is no shared parsing for booleans, ints, or paths.

We expect more knobs over time. The fix is a single, composed settings object that flows explicitly through `create_app`, with env-var loading as one constructor among others (so tests can override via env, via typed `replace()`, or via a literal `Settings(...)`).

## Goals

- One source of truth (`novamoc.config`) for every runtime knob. The existing `config.py` module gains the dataclasses; the file keeps its current name to avoid a churn-only rename and because "config" is the natural home for `Settings` plus path resolution alongside.
- Settings objects are **frozen dataclasses** (matches `ServiceBundle`'s pattern). No global mutable state, no module-level cache.
- Composed by concern: `DatabaseSettings`, `ServerSettings`, `ProblemSettings` aggregate into a top-level `Settings`. (`AccountsSettings` is intentionally absent in v1 — see Non-goals.)
- Production wiring: `create_app(settings: Settings | None = None)`; if `None`, calls `Settings()` — env-aware field default factories on the child dataclasses do the loading.
- Test wiring: a `settings` pytest fixture builds a test-flavoured `Settings(...)` literal; `app` fixture calls `create_app(settings=settings)`. Per-test overrides use either `dataclasses.replace` or `monkeypatch.setenv` + a fresh `Settings()`.
- Env vars follow `NOVAMOC_<SECTION>_<FIELD>`. The existing `NOVAMOC_PROBLEM_DOCS_BASE_URL` already matches this pattern (`PROBLEM` section, `DOCS_BASE_URL` field), so it's kept verbatim — coincidence, not compatibility.

## Non-goals

- **No `pydantic-settings` / `dynaconf` dependency.** The repo uses `msgspec` for wire types and frozen `@dataclass` for in-memory aggregates; the settings module follows the latter.
- **No dotenv in v1.** Production is expected to receive real env vars from the deployment; tests build `Settings(...)` literals or use `monkeypatch.setenv`. A `python-dotenv` layer can be added later as a one-line `load_dotenv()` at process start without changing the module's public surface.
- **No runtime hot-reload.** `Settings` is built once per process (or per test), and that's the snapshot the app sees.
- **No secrets management.** The dev tenant token (`_TENANT_T1_DEV_TOKEN` in `domain/accounts/_resolver.py`) stays a module-level constant — it is dev-only credentialling for issue #19's pre-auth shim, not something operators tune at runtime. Real auth credentials are out of scope; when they arrive they get their own home (likely a secrets-manager-backed loader, not env vars).
- **No `AccountsSettings` section in v1.** The only candidate field would have been the dev token above, and that is staying a constant. Adding an empty section just to reserve the name is YAGNI; it can be added when a real per-deployment accounts knob shows up.
- **No per-request / per-tenant settings.** Tenant scoping uses the contextvar mechanism (ADR-014, issue #51); settings are process-level.

## Module shape

```
src/py/novamoc/config.py                              # existing module, expanded
├── problem_html_dir() -> Path                        # unchanged, filesystem path resolver
├── _str_env(name, default) -> Callable[[], str]      # field-default factory helper
├── _bool_env(name, default) -> Callable[[], bool]    # field-default factory helper
├── _to_bool(value, *, default) -> bool               # parsing primitive
├── DatabaseSettings        (frozen dataclass; field defaults read env)
├── ServerSettings          (frozen dataclass; field defaults read env)
├── ProblemSettings         (frozen dataclass; field defaults read env)
└── Settings                (frozen dataclass aggregating the above)
```

All four dataclasses use `@dataclass(frozen=True, slots=True)`. There are no `from_env` classmethods — env loading lives in each field's `default_factory`. Calling `DatabaseSettings()` (or any other constructor with no args) reads env once for each unset field and returns a frozen instance.

### Fields and defaults

| Section / field | Default | Env var |
|---|---|---|
| `DatabaseSettings.url` | `"sqlite+aiosqlite:///novamoc.sqlite"` | `NOVAMOC_DB_URL` |
| `DatabaseSettings.static_pool` | `False` | `NOVAMOC_DB_STATIC_POOL` |
| `DatabaseSettings.create_all` | `True` | `NOVAMOC_DB_CREATE_ALL` |
| `DatabaseSettings.before_send_handler` | `"autocommit"` | `NOVAMOC_DB_BEFORE_SEND_HANDLER` |
| `ServerSettings.granian` | `True` | `NOVAMOC_SERVER_GRANIAN` |
| `ProblemSettings.docs_base_url` | `"http://localhost:8000"` | `NOVAMOC_PROBLEM_DOCS_BASE_URL` |

The naming pattern is `NOVAMOC_<SECTION>_<FIELD>` everywhere. `NOVAMOC_PROBLEM_DOCS_BASE_URL` already matches it.

### Parsing rules

- **Strings**: passthrough (`_str_env(name, default)` returns `lambda: os.environ.get(name, default)`).
- **Booleans**: `_to_bool(value, *, default)` returns `default` when `value is None` (env var unset); accepts `{"true", "false", "1", "0"}` case-insensitively when set; raises `ValueError` for any other set-but-unparseable string. No magic truthiness on arbitrary strings — a typo like `NOVAMOC_DB_STATIC_POOL=yes` is a startup failure, not a silent default. `_bool_env(name, default)` wraps it in a factory: `lambda: _to_bool(os.environ.get(name), default=default)`.
- **Ints / paths / lists**: not used today. When introduced, each gets its own `_<type>_env` factory helper paired with a `_to_<type>` parsing primitive — explicit beats clever.

### Default-value changes from current code

The production default database path is renamed from `test.sqlite` (current `asgi.py` literal) to `novamoc.sqlite`. The old name is a scaffolding leftover; settings v1 is when it gets fixed.

### Field default factories

Each field carries its own env-reading `default_factory`. The literal fallback lives in the factory call — there is no second "defaults" pass:

```python
def _str_env(name: str, default: str) -> Callable[[], str]:
    return lambda: os.environ.get(name, default)


def _bool_env(name: str, default: bool) -> Callable[[], bool]:
    return lambda: _to_bool(os.environ.get(name), default=default)


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = field(default_factory=_str_env("NOVAMOC_DB_URL", "sqlite+aiosqlite:///novamoc.sqlite"))
    static_pool: bool = field(default_factory=_bool_env("NOVAMOC_DB_STATIC_POOL", False))
    create_all: bool = field(default_factory=_bool_env("NOVAMOC_DB_CREATE_ALL", True))
    before_send_handler: str = field(default_factory=_str_env("NOVAMOC_DB_BEFORE_SEND_HANDLER", "autocommit"))


@dataclass(frozen=True, slots=True)
class Settings:
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    problem: ProblemSettings = field(default_factory=ProblemSettings)
```

`Settings()` is the only entry point. It builds three children; each child constructor invokes its field factories; each factory reads env once and falls back to the literal default. Two consequences worth understanding:

- **Constructing a settings instance has a side effect** — it reads `os.environ` at call time. That is the whole point: re-reading env without a global cache is what makes `monkeypatch.setenv` + `Settings()` Just Work in tests, and what makes import order irrelevant.
- **Partial overrides re-read env for unset fields.** `DatabaseSettings(url="x")` reads env for `static_pool`, `create_all`, and `before_send_handler`. Tests that want a hermetic baseline pass every field explicitly (the `settings` fixture below does this), or build their settings via `replace()` against a known-good base.

## Production wiring

`asgi.create_app` becomes:

```python
def create_app(settings: Settings | None = None) -> Litestar:
    s = settings if settings is not None else Settings()

    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string=s.db.url,
        before_send_handler=s.db.before_send_handler,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=s.db.create_all,
        engine_config=EngineConfig(poolclass=StaticPool) if s.db.static_pool else EngineConfig(),
    )

    plugins: list[PluginProtocol] = [
        SQLAlchemyPlugin(config=alchemy_config),
        ProblemDetailsPlugin(config=_problem_details_config(s.problem.docs_base_url)),
    ]
    if s.server.granian:
        plugins.insert(0, GranianPlugin())

    return Litestar(
        route_handlers=[SchemaController, _problem_docs_router()],
        middleware=[
            DefineMiddleware(AuthenticationMiddleware, exclude=r"^/(openapi|problems)"),
            TenantContextMiddleware(),
        ],
        plugins=plugins,
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
```

The `before_send_handler`, `create_all`, and `static_pool` knobs were previously hardcoded in `asgi.py`; they move into `DatabaseSettings` so tests can flip `static_pool` without rebuilding the rest. `granian=True` is the production default (boolean instead of branching on a config object — the plugin set varies, not the SQLAlchemy plugin's shape).

### Plumbing settings into consumers

One consumer currently reads configuration from outside `create_app`:

- **`api/_problem_details.py`** — `_type_uri()` calls `problem_docs_base_url()` to render the per-error type URI. The converter functions (`schema_error_to_problem_details`, etc.) need access to the configured base URL.

It moves to a factory pattern: the module exposes builders (`make_schema_error_converter(base_url)`, etc.) that close over the settings value, and `create_app` constructs the closures with `s.problem.docs_base_url`. This keeps the settings type out of `_problem_details.py`'s import graph and makes the dependency on settings explicit at the construction site.

`domain/accounts/_resolver.py` is intentionally not changed: `_TENANT_T1_DEV_TOKEN` stays a module-level constant (dev-only credential, see Non-goals).

For consumers that legitimately need ambient access (e.g., a future audit logger that fires from deep inside a handler), we can add a `Settings` `ContextVar` later; the v1 surface keeps things explicit.

### `config.py` after migration

`config.py` is the home for both the new dataclasses and the existing `problem_html_dir()` helper. The function-style `problem_docs_base_url()` is removed; its single responsibility moves into `ProblemSettings.docs_base_url`. The existing `tests/test_config.py` keeps its name and gains the new dataclass tests; the two `problem_docs_base_url`-specific tests are replaced by their `Settings`-flavoured equivalents.

Path-resolution helpers (today: just `problem_html_dir()`) and runtime-knob dataclasses live in the same file because the file is small and the two roles read together as "module-level knobs." If the path-resolution layer grows, splitting it into `paths.py` is a one-PR refactor — not justified yet.

## Test wiring

`tests/conftest.py` shrinks substantially:

```python
@pytest.fixture
def settings() -> Settings:
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
    return create_app(settings=settings)
```

The whole `app` fixture's manual Litestar construction goes away. `_problem_docs_base_url` (the autouse session fixture that pins `NOVAMOC_PROBLEM_DOCS_BASE_URL`) is removed — the `settings` fixture does that job by literal value, no env-var manipulation needed.

### Per-test override patterns

**Typed override** (preferred when the field is known at edit time):

```python
async def test_alt_docs_base(settings: Settings):
    s = replace(settings, problem=replace(settings.problem, docs_base_url="http://alt"))
    app = create_app(settings=s)
    ...
```

**Env-var override** (preferred when interleaving with other env-driven test bootstrapping or when the test thinks in env-var terms):

```python
async def test_alt_docs_base(monkeypatch):
    monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://alt")
    settings = Settings()  # field factories re-read env now
    app = create_app(settings=settings)
```

There's no cache to clear because there is no cache. `monkeypatch` restores env on test teardown. Both patterns are first-class.

**Parametrization**:

```python
@pytest.fixture
def settings(request) -> Settings:
    return replace(BASE_TEST_SETTINGS, problem=replace(BASE_TEST_SETTINGS.problem, docs_base_url=request.param))

@pytest.mark.parametrize("settings", ["http://a", "http://b"], indirect=True)
async def test_two_doc_bases(app: Litestar): ...
```

## Why explicit injection rather than the cached-singleton pattern

The litestar-fullstack approach (`@lru_cache`'d `get_settings()`, env vars set as the first executable lines of `tests/conftest.py`) is well-trodden, but it couples three concerns we'd rather keep separate: (1) where settings live, (2) when they're loaded, and (3) how they're overridden. Cache invalidation across tests, import-ordering rules at the top of conftest, and the inability to parametrize without `cache_clear()` are all symptoms of that coupling.

The frozen-dataclass-plus-injection model decouples them: `Settings()` reads env *every* time it's constructed (no cache), and the override mechanism is "build a different `Settings` and pass it in." Env-var convenience (dotenv, `monkeypatch.setenv`, CI env injection) is preserved because env vars are still the production source — just no longer the only entry point.

## Architecture impact

This change is a refactor, not a feature: the wire contract, database schema, and ADRs are all unchanged. No new ADR is needed; the settings module is a Python organisational concern, not an architectural decision.

## Migration plan (high-level)

A separate plan document (`docs/superpowers/plans/2026-05-07-settings-module.md`) will detail the steps; expected shape:

1. Extend `src/py/novamoc/config.py` with the dataclasses, `_str_env` / `_bool_env` factory helpers, and `_to_bool` parsing primitive (alongside the existing `problem_html_dir()`). Extend `tests/test_config.py` with the new coverage: literal defaults, env reads, boolean parsing rejects garbage, partial-construction re-reads env for unset fields.
2. Migrate `_problem_details.py` to factory functions accepting the configured base URL.
3. Update `asgi.create_app` to take optional `Settings`, build alchemy config from it, conditionally include `GranianPlugin`, and wire the converter factories.
4. Replace the test `app` fixture's parallel construction with `create_app(settings=settings)`. Remove the `_problem_docs_base_url` autouse fixture.
5. Delete `problem_docs_base_url()` from `config.py`; remove its two tests (the new `ProblemSettings` tests cover the same behaviour).

Each step compiles, lints, and passes tests in isolation, so they can land as separate commits.
