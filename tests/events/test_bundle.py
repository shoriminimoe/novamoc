"""Tests for EventServiceBundle: cache hit/miss accounting and content."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._payloads import EntityFamily
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_TRUCK_WITH_VIN_FIELD

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class _CountingAssetTypeFieldService(AssetTypeFieldService):
    """Spy that counts list() invocations for the cache-hit test."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.list_calls = 0

    async def list(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        self.list_calls += 1
        return await super().list(*args, **kwargs)


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=_CountingAssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
    )


async def test_fields_for_returns_type_fields_keyed_by_id(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    fields_by_id = await event_services.fields_for(EntityFamily.ASSET, type_id)
    assert set(fields_by_id) == set(ids["asset_type_field"].values())
    assert all(f.parent_id == type_id for f in fields_by_id.values())


async def test_fields_for_is_memoised_per_key(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    first = await event_services.fields_for(EntityFamily.ASSET, type_id)
    second = await event_services.fields_for(EntityFamily.ASSET, type_id)
    assert first is second  # same dict object on second call
    spy = event_services.asset_type_field_service
    assert isinstance(spy, _CountingAssetTypeFieldService)
    assert spy.list_calls == 1


async def test_fields_for_routes_to_family_specific_service(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    # Loading asset fields must not touch the maintenance-record service.
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    await event_services.fields_for(EntityFamily.ASSET, type_id)
    spy = event_services.asset_type_field_service
    assert isinstance(spy, _CountingAssetTypeFieldService)
    assert spy.list_calls == 1
