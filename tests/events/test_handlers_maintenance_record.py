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
    Parent,
    Updated,
)
from novamoc.domain.events.services import EventLogService
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    MaintenanceRecordTypeFieldService,
)
from tests._constants import DEV_TENANT_ID
from tests.data.scenarios import (
    ACTIVE_OIL_CHANGE_WITH_NOTES,
    ACTIVE_OIL_CHANGE_WITH_NOTES_AND_RECORD,
    ACTIVE_TRUCK_WITH_ASSET,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_HLC = "0000000000000001-00000-client-a"


def _auth() -> RequestAuth:
    return RequestAuth(tenant_id=DEV_TENANT_ID)


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
    *,
    instance_id: UUID | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        hlc=_HLC,
        family=EntityFamily.MAINTENANCE_RECORD,
        type_id=type_id,
        instance_id=instance_id or uuid4(),
        body=body,
    )


async def test_created_with_valid_values(
    event_services: EventServiceBundle,
    seed: Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]],
) -> None:
    # Seed both the MR type+field schema (for the field validation) AND a
    # parent asset (so the MR's FK into ``assets`` resolves). The two
    # scenarios share the truck/asset_type atom — ``ACTIVE_TRUCK_WITH_ASSET``
    # subsumes it.
    ids = await seed(ACTIVE_TRUCK_WITH_ASSET)
    parent_asset_id = ids["asset"]["Primary Truck"]
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    body = Created(
        parent=Parent(type_id=uuid4(), instance_id=parent_asset_id),
        values={str(field_id): "All filters replaced."},
    )
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
    # Updated has no row-state component, so the MR row must exist for
    # the field-value fold's FK into ``maintenance_records`` to resolve.
    ids = await seed(ACTIVE_OIL_CHANGE_WITH_NOTES_AND_RECORD)
    type_id = ids["maintenance_record_type"]["OilChange"]
    field_id = ids["maintenance_record_type_field"]["notes"]
    record_id = ids["maintenance_record"]["Primary Oil Change"]
    body = Updated(values={str(field_id): None})
    await maintenance_record.updated(
        event_services, _auth(), _envelope(type_id, body, instance_id=record_id)
    )


async def test_deactivated_appends(event_services: EventServiceBundle) -> None:
    body = Deactivated()
    outcome = await maintenance_record.deactivated(
        event_services, _auth(), _envelope(uuid4(), body)
    )
    assert outcome.outcome == "accepted"


async def test_activated_appends(event_services: EventServiceBundle) -> None:
    body = Activated()
    outcome = await maintenance_record.activated(
        event_services, _auth(), _envelope(uuid4(), body)
    )
    assert outcome.outcome == "accepted"
