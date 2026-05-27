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

from advanced_alchemy.extensions.litestar import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
)
from sqlalchemy.pool import StaticPool

from novamoc.config import Settings


def _migrations_dir() -> str:
    """Resolve ``src/py/novamoc/db/migrations`` for both wheel and editable installs."""
    return str(files("novamoc.db") / "migrations")


def build_alchemy_config(settings: Settings) -> SQLAlchemyAsyncConfig:
    """Build the per-app ``SQLAlchemyAsyncConfig`` from ``settings``."""
    engine_config = (
        EngineConfig(poolclass=StaticPool)
        if settings.db.static_pool
        else EngineConfig()
    )
    return SQLAlchemyAsyncConfig(
        connection_string=settings.db.url,
        # ty narrows the literal-arg type to ``Literal["autocommit", ...]``;
        # ``settings.db.before_send_handler`` is a plain ``str`` from the
        # ``DatabaseSettings`` field, validated by advanced_alchemy at runtime.
        before_send_handler=settings.db.before_send_handler,  # ty: ignore[invalid-argument-type]
        session_config=AsyncSessionConfig(expire_on_commit=False),
        engine_config=engine_config,
        alembic_config=AlembicAsyncConfig(script_location=_migrations_dir()),
    )


alchemy_config = build_alchemy_config(Settings())
"""Module-level instance for ``alchemy --config novamoc.db.config.alchemy_config``.

``Settings()`` reads env vars at import time. CLI processes pick up
``NOVAMOC_DB_URL`` etc. without ceremony; the test process imports
this transitively but does not consume it (tests build their own
config via :func:`build_alchemy_config`).
"""
