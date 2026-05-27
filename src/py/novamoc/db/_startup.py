"""Alembic-revision startup gate.

Reads the database's current Alembic revision and compares it to the
script tree's HEAD. Raises :class:`AlembicRevisionMismatchError` when
they disagree (including the "no ``alembic_versions`` table" case,
the "connection failed" case, and the "multiple heads in the script
tree" case), naming the remediation in the message.

Wired into ``create_app``'s ``on_startup`` list so a misconfigured
deployment fails at process boot rather than at first SQL query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig


# Mention both surfaces so the message lands cleanly in any context:
# contributors / dev shells see ``just db-init``; production init
# containers (which typically don't ship ``just``) see the raw
# advanced-alchemy invocation with ``--no-prompt`` so it's paste-safe
# in non-TTY environments.
_REMEDIATION = (
    "apply pending Alembic migrations "
    "(``just db-init`` locally, or "
    "``uv run alchemy --config novamoc.db.config.alchemy_config "
    "upgrade head --no-prompt`` in production)"
)


class AlembicRevisionMismatchError(RuntimeError):
    """Raised when the DB's revision does not match the script tree's HEAD."""


async def assert_alembic_at_head(alchemy_config: SQLAlchemyAsyncConfig) -> None:
    """Refuse to serve if the database is not at HEAD.

    Args:
        alchemy_config: The same config the Litestar plugin is bound to;
            its engine and ``alembic_config.script_location`` are read.

    Raises:
        AlembicRevisionMismatchError: One of:

            * Database is empty (no ``alembic_versions`` table).
            * Database is reachable but at a revision other than HEAD.
            * Connection to the database failed (``OperationalError``).
            * Migration tree has multiple heads (a transient state
              after a branched merge — the operator must run
              ``alchemy merge`` before deploying).
    """
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option(
        "script_location", alchemy_config.alembic_config.script_location
    )
    script_dir = ScriptDirectory.from_config(alembic_cfg)
    heads = script_dir.get_heads()
    if len(heads) != 1:
        msg = (
            f"Migration tree has {len(heads)} heads ({heads!r}); "
            f"expected exactly one. Resolve branched migrations via "
            f"``alchemy merge`` before deploying."
        )
        raise AlembicRevisionMismatchError(msg)
    head = heads[0]

    version_table = alchemy_config.alembic_config.version_table_name
    engine = alchemy_config.get_engine()
    try:
        async with engine.connect() as conn:
            current = await conn.run_sync(
                lambda sync_conn: MigrationContext.configure(
                    sync_conn, opts={"version_table": version_table}
                ).get_current_revision()
            )
    except OperationalError as exc:
        msg = (
            f"Could not connect to the database to verify the Alembic "
            f"revision: {exc}. Resolve the connection error and then "
            f"{_REMEDIATION}."
        )
        raise AlembicRevisionMismatchError(msg) from exc

    if current != head:
        msg = (
            f"Database schema at revision {current!r} but app expects "
            f"{head!r}. {_REMEDIATION.capitalize()}."
        )
        raise AlembicRevisionMismatchError(msg)
