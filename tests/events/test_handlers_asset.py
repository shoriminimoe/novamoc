"""Handler-level tests for the asset family event handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.domain.accounts import RequestAuth
from novamoc.domain.events._bundle import EventServiceBundle
from novamoc.domain.events._errors import (
    UnknownFieldError,
    ValueTypeMismatchError,
)
from novamoc.domain.events._handlers import asset
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_TRUCK_WITH_VIN_FIELD

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_HLC = "0000000000000001-00000-client-a"


def _auth() -> RequestAuth:
    return RequestAuth(tenant_id="t1")


@pytest.fixture
def event_services(session: AsyncSession) -> EventServiceBundle:
    return EventServiceBundle(
        asset_type_field_service=AssetTypeFieldService(session=session),
        maintenance_record_type_field_service=MaintenanceRecordTypeFieldService(
            session=session
        ),
        event_log_service=EventLogService(session=session),
        schema_version=0,
    )


def _envelope(
    type_id: UUID,
    body: Created | Updated | Deactivated | Activated,
) -> EventEnvelope:
    return EventEnvelope(
        hlc=_HLC,
        family=EntityFamily.ASSET,
        type_id=type_id,
        instance_id=uuid4(),
        body=body,
    )


async def test_created_with_valid_values(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    field_id = ids["asset_type_field"]["vin"]
    body = Created(values={str(field_id): "ABC123"})
    await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_unknown_field_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    body = Created(values={str(uuid4()): "x"})
    with pytest.raises(UnknownFieldError):
        await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_wrong_value_type_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    field_id = ids["asset_type_field"]["vin"]
    body = Created(values={str(field_id): 42})
    with pytest.raises(ValueTypeMismatchError):
        await asset.created(event_services, _auth(), _envelope(type_id, body))


async def test_updated_validates_like_created(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_TRUCK_WITH_VIN_FIELD)
    type_id = ids["asset_type"]["Truck"]
    field_id = ids["asset_type_field"]["vin"]
    body = Updated(values={str(field_id): None})  # null clears
    await asset.updated(event_services, _auth(), _envelope(type_id, body))


async def test_deactivated_appends(event_services: EventServiceBundle) -> None:
    body = Deactivated()
    outcome = await asset.deactivated(event_services, _auth(), _envelope(uuid4(), body))
    assert outcome.outcome == "accepted"


async def test_activated_appends(event_services: EventServiceBundle) -> None:
    body = Activated()
    outcome = await asset.activated(event_services, _auth(), _envelope(uuid4(), body))
    assert outcome.outcome == "accepted"
