"""Scenario loader for the test-data fixtures.

Reads atoms (JSON files under ``fixtures/<entity>/``) named by a
:data:`Scenario` tuple and inserts them via the matching
:class:`ServiceBundle` attribute. Never commits — composes with the
``session`` fixture's rollback at teardown.

Layout convention: each atom path is ``<entity>/<basename>``. The entity
directory groups all fixtures for one logical entity (e.g., everything
about a Truck lives under ``truck/``). The basename is
``<service_attr>[__<variant>]`` — the prefix names the target service on
:class:`ServiceBundle`, the optional ``__variant`` suffix distinguishes
multiple fixtures targeting the same service from the same entity.
Examples: ``truck/asset_type``, ``truck/asset_type__deactivated``,
``truck/asset_type_field__vin``.

Export inference: every schema entity has a unique-per-tenant ``name``
column, so ``exports[service_attr][row["name"]]`` is well-defined for
the entities we seed today. When data-side fixtures arrive, rows
without a ``name`` will need a different keying rule — decide that
when the first such scenario is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from advanced_alchemy.utils.fixtures import open_fixture_async
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema._bundle import ServiceBundle
from tests.data.scenarios import Scenario

FIXTURES_PATH: Path = Path(__file__).parent / "fixtures"


def _service_attr_for(basename: str) -> str:
    """Extract the service attribute from an atom basename.

    The prefix before ``__`` (or the whole basename if no ``__``) is the
    target :class:`ServiceBundle` attribute. ``asset_type`` →
    ``asset_type``; ``asset_type_field__vin`` → ``asset_type_field``.
    """
    return basename.partition("__")[0]


async def load_scenario(
    scenario: Scenario,
    *,
    session: AsyncSession,
    services: ServiceBundle,
) -> Mapping[str, Mapping[str, UUID]]:
    """Load the given scenario into ``session`` via ``services``.

    Returns ``{service_attr: {row_name: UUID(row_id)}}`` so callers can
    refer to seeded entities by name without hard-coding UUIDs.
    """
    exports: dict[str, dict[str, UUID]] = {}

    for path in scenario:
        entity_dir, basename = path.split("/", 1)
        service_attr = _service_attr_for(basename)
        rows = await open_fixture_async(FIXTURES_PATH / entity_dir, basename)
        await getattr(services, service_attr).create_many(
            data=rows,
            auto_commit=False,
        )
        bucket = exports.setdefault(service_attr, {})
        for row in rows:
            bucket[row["name"]] = UUID(row["id"])

    await session.flush()
    return exports
