"""Handler-level tests for the maintenance-record family event handlers."""

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
from novamoc.domain.events._handlers import maintenance_record
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests.data.scenarios import ACTIVE_OIL_CHANGE_WITH_NOTES

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
    )


def _envelope(
    type_id: UUID,
    body: Created | Updated | Deactivated | Activated,
) -> EventEnvelope:
    return EventEnvelope(
        hlc=_HLC,
        family=EntityFamily.MAINTENANCE_RECORD,
        type_id=type_id,
        instance_id=uuid4(),
        body=body,
    )


async def test_created_with_valid_values(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Created(values={str(field_id): "All filters replaced."})
    await maintenance_record.created(event_services, _auth(), _envelope(type_id, body))


async def test_created_with_unknown_field_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    body = Created(values={str(uuid4()): "x"})
    with pytest.raises(UnknownFieldError):
        await maintenance_record.created(
            event_services, _auth(), _envelope(type_id, body)
        )


async def test_created_with_wrong_value_type_raises(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Created(values={str(field_id): 42})
    with pytest.raises(ValueTypeMismatchError):
        await maintenance_record.created(
            event_services, _auth(), _envelope(type_id, body)
        )


async def test_updated_validates_like_created(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Updated(values={str(field_id): None})
    await maintenance_record.updated(event_services, _auth(), _envelope(type_id, body))


async def test_deactivated_is_noop(event_services: EventServiceBundle) -> None:
    body = Deactivated()
    await maintenance_record.deactivated(
        event_services, _auth(), _envelope(uuid4(), body)
    )


async def test_activated_is_noop(event_services: EventServiceBundle) -> None:
    body = Activated()
    await maintenance_record.activated(
        event_services, _auth(), _envelope(uuid4(), body)
    )
