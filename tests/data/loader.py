"""Scenario loader for the test-data fixtures.

Reads atoms (JSON files under ``fixtures/<entity>/``) named by a
:data:`Scenario` tuple and inserts them. Never commits — composes
with the ``session`` fixture's rollback at teardown.

Two dispatch paths, keyed off the atom's basename prefix:

* **Service-backed atoms** (schema entities — ``asset_type``,
  ``asset_type_field``, ``maintenance_record_type``,
  ``maintenance_record_type_field``) — inserted via the matching
  :class:`ServiceBundle` attribute's ``create_many``. Tenant-id
  stamping is handled by the schema service layer.
* **Model-backed atoms** (data entities — ``asset``,
  ``maintenance_record``) — inserted via direct ORM ``session.add``
  against the model class. Data-projection tables don't have a
  command/service surface (their rows are normally produced by
  folding the event log); the ORM add path triggers the layer-2
  ``before_flush`` listener which auto-stamps ``tenant_id`` from
  the ambient ``current_tenant_id`` ContextVar, so the bypass is
  safe for tests that only need a parent row to satisfy a FK.

Layout convention: each atom path is ``<entity>/<basename>``. The
entity directory groups all fixtures for one logical entity (e.g.,
everything about a Truck lives under ``truck/``). The basename is
``<service_attr>[__<variant>]`` — the prefix names the target
service or model, the optional ``__variant`` suffix distinguishes
multiple fixtures targeting the same target from the same entity.

Export inference: rows are exported under ``row["name"]``. Every
schema entity has a unique-per-tenant ``name`` column; data-entity
fixtures set a non-null ``name`` for the same reason (so tests can
look the UUID up without hard-coding it).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.utils.fixtures import open_fixture_async

from novamoc.db.models.data import Asset, MaintenanceRecord

if TYPE_CHECKING:
    from collections.abc import Mapping

    from advanced_alchemy.base import DefaultBase, UUIDAuditBase
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.schema._bundle import ServiceBundle
    from tests.data.scenarios import Scenario

FIXTURES_PATH: Path = Path(__file__).parent / "fixtures"

# Data entities don't have a command/service surface; loader dispatches
# to ORM ``session.add`` against the model class. The before_flush
# listener auto-stamps ``tenant_id`` from ``current_tenant_id``.
_DATA_MODELS: dict[str, type[DefaultBase | UUIDAuditBase]] = {
    "asset": Asset,
    "maintenance_record": MaintenanceRecord,
}


def _service_attr_for(basename: str) -> str:
    """Extract the service attribute from an atom basename.

    The prefix before ``__`` (or the whole basename if no ``__``) is
    the target. ``asset_type`` → ``asset_type``;
    ``asset_type_field__vin`` → ``asset_type_field``.
    """
    return basename.partition("__")[0]


async def load_scenario(
    scenario: Scenario,
    *,
    session: AsyncSession,
    services: ServiceBundle,
) -> Mapping[str, Mapping[str, UUID]]:
    """Load the given scenario into ``session`` via ``services``.

    Returns ``{service_or_model_attr: {row_name: UUID(row_id)}}`` so
    callers can refer to seeded entities by name without hard-coding
    UUIDs.
    """
    exports: dict[str, dict[str, UUID]] = {}

    for path in scenario:
        entity_dir, basename = path.split("/", 1)
        attr = _service_attr_for(basename)
        rows = await open_fixture_async(FIXTURES_PATH / entity_dir, basename)
        if hasattr(services, attr):
            await getattr(services, attr).create_many(
                data=rows,
                auto_commit=False,
            )
        elif attr in _DATA_MODELS:
            model = _DATA_MODELS[attr]
            for row in rows:
                session.add(model(**row))
        else:
            msg = (
                f"unknown service or data model for atom basename {basename!r} "
                f"(path {path!r})"
            )
            raise ValueError(msg)
        bucket = exports.setdefault(attr, {})
        for row in rows:
            bucket[row["name"]] = UUID(row["id"])

    await session.flush()
    return exports
