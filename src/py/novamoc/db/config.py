"""Single chokepoint for ``SQLAlchemyAsyncConfig`` construction.

Imports the Litestar-flavored ``SQLAlchemyAsyncConfig`` because the
Litestar plugin requires that subclass at registration time, and the
advanced-alchemy CLI accepts it polymorphically. This is the second
documented carve-out to the "db/ must not depend on Litestar" rule
(see ``db/models/_auth/_session.py`` for the first); see CLAUDE.md
"Critical layering rule".
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from advanced_alchemy.extensions.litestar import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
)
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from novamoc.config import Settings
from novamoc.db._pragmas import register_sqlite_pragmas


def _migrations_dir() -> str:
    """Resolve ``src/py/novamoc/db/migrations`` for both wheel and editable installs."""
    return str(files("novamoc.db") / "migrations")


def build_alchemy_config(settings: Settings) -> SQLAlchemyAsyncConfig:
    """Build the per-app ``SQLAlchemyAsyncConfig`` from ``settings``."""
    # ``make_url`` is SQLAlchemy's public URL parser; ``get_backend_name()``
    # returns the dialect regardless of ``+driver`` suffix or case
    # normalisation, so the check is robust against
    # ``SQLITE+aiosqlite://...`` and similar variants. Used to gate both
    # the SQLite-specific connect_args and the WAL/pragma registration.
    sqlite_url = make_url(settings.db.url).get_backend_name() == "sqlite"
    engine_config_kwargs: dict[str, Any] = {}
    if settings.db.static_pool:
        engine_config_kwargs["poolclass"] = StaticPool
    if sqlite_url:
        # ``sqlite3.connect(timeout=...)`` maps to SQLite's per-connection
        # ``busy_timeout`` — the retry budget for write-lock contention.
        # Defence in depth alongside the request-scoped session backend
        # (see novamoc#123); tunable via
        # ``DatabaseSettings.busy_timeout_seconds`` /
        # ``NOVAMOC_DB_BUSY_TIMEOUT_SECONDS``.
        engine_config_kwargs["connect_args"] = {
            "timeout": settings.db.busy_timeout_seconds
        }
    engine_config = EngineConfig(**engine_config_kwargs)
    cfg = SQLAlchemyAsyncConfig(
        connection_string=settings.db.url,
        # ty narrows the literal-arg type to ``Literal["autocommit", ...]``;
        # ``settings.db.before_send_handler`` is a plain ``str`` from the
        # ``DatabaseSettings`` field, validated by advanced_alchemy at runtime.
        before_send_handler=settings.db.before_send_handler,  # ty: ignore[invalid-argument-type]
        session_config=AsyncSessionConfig(expire_on_commit=False),
        engine_config=engine_config,
        alembic_config=AlembicAsyncConfig(script_location=_migrations_dir()),
    )
    # SQLite per-driver options (WAL + foreign_keys today; ``synchronous=NORMAL``
    # etc. later) attach to the specific engine instance. The per-engine
    # registration means the listener body in ``_pragmas`` doesn't need any
    # driver-class detection.
    if sqlite_url:
        register_sqlite_pragmas(cfg.get_engine())
    return cfg


# Lazy module-level ``alchemy_config`` instance for
# ``alchemy --config novamoc.db.config.alchemy_config``. PEP 562's module
# ``__getattr__`` defers ``Settings()`` env-var parsing and ``AsyncEngine``
# construction to first access — pytest collection and any code path that
# never touches the CLI surface no longer pay either cost, and a typo'd env
# var (``NOVAMOC_AUTH_ARGON2_TIME_COST=oops``) no longer crashes import.
_alchemy_config: SQLAlchemyAsyncConfig | None = None


def __getattr__(name: str) -> SQLAlchemyAsyncConfig:
    """Resolve ``alchemy_config`` on demand.

    The advanced-alchemy CLI's ``--config`` flag does an attribute lookup
    on the imported module; PEP 562 lets us intercept the lookup and run
    ``build_alchemy_config(Settings())`` lazily.
    """
    global _alchemy_config  # noqa: PLW0603
    if name == "alchemy_config":
        if _alchemy_config is None:
            _alchemy_config = build_alchemy_config(Settings())
        return _alchemy_config
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
