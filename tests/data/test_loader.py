"""Tests for the scenario loader.

These run against the same in-memory ``session`` + ``services`` fixtures
the schema-handler tests use (see ``tests/conftest.py``), so they verify
the loader integrates with the real ``ServiceBundle`` path rather than a
mock.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema._bundle import ServiceBundle
from tests.data.loader import load_scenario
from tests.data.scenarios import (
    ACTIVE_TRUCK,
    ACTIVE_TRUCK_WITH_VIN_FIELD,
    DEACTIVATED_TRUCK,
)

_TENANT = "t1"


async def test_load_scenario_inserts_rows(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    ids = await load_scenario(ACTIVE_TRUCK, session=session, services=services)
    truck_id = ids["asset_type"]["Truck"]
    row = await services.asset_type.get_one_or_none(tenant_id=_TENANT, id=truck_id)
    assert row is not None
    assert row.name == "Truck"
    assert row.active is True


async def test_load_scenario_returns_exports_keyed_by_service_and_name(
    session: AsyncSession,
    services: ServiceBundle,
) -> None:
    exports = await load_scenario(
        ACTIVE_TRUCK,
        session=session,
        services=services,
    )
    assert exports.keys() == {"asset_type"}
    assert exports["asset_type"].keys() == {"Truck"}
    assert isinstance(exports["asset_type"]["Truck"], UUID)


async def test_seed_fixture_loads_scenario(seed, services: ServiceBundle) -> None:
    ids = await seed(ACTIVE_TRUCK)
    truck_id = ids["asset_type"]["Truck"]
    row = await services.asset_type.get_one_or_none(tenant_id=_TENANT, id=truck_id)
    assert row is not None and row.name == "Truck"


async def test_load_multi_atom_scenario_respects_parent_child_order(
    seed,
    services: ServiceBundle,
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    assert ids.keys() == {"asset_type", "asset_type_field"}
    assert ids["asset_type"].keys() == {"Truck"}
    assert ids["asset_type_field"].keys() == {"vin"}
    truck_id = ids["asset_type"]["Truck"]
    vin_id = ids["asset_type_field"]["vin"]
    field = await services.asset_type_field.get_one_or_none(
        tenant_id=_TENANT,
        id=vin_id,
    )
    assert field is not None
    assert field.parent_id == truck_id
    assert field.name == "vin"
    assert field.data_type == "text"
    assert field.validation is None
    assert field.active is True


async def test_missing_atom_file_raises_file_not_found(
    session: AsyncSession, services: ServiceBundle
) -> None:
    """A scenario referencing a non-existent atom must surface the
    underlying ``FileNotFoundError`` rather than being swallowed by the
    loader."""
    with pytest.raises(FileNotFoundError):
        await load_scenario(
            ("nope/asset_type",),
            session=session,
            services=services,
        )


async def test_deactivated_truck_scenario(seed, services: ServiceBundle) -> None:
    ids = await seed(DEACTIVATED_TRUCK)
    truck_id = ids["asset_type"]["Truck"]
    row = await services.asset_type.get_one_or_none(tenant_id=_TENANT, id=truck_id)
    assert row is not None
    assert row.active is False
