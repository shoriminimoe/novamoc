from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
)


@pytest.mark.parametrize(
    "service_cls",
    [
        AssetTypeService,
        MaintenanceRecordTypeService,
    ],
)
async def test_type_service_round_trip(service_cls, session: AsyncSession) -> None:
    svc = service_cls(session=session)
    eid = uuid4()
    obj = await svc.create(
        data={"tenant_id": "t1", "id": eid, "name": "X", "active": True},
        auto_commit=False,
    )
    await session.flush()
    fetched = await svc.get_one_or_none(tenant_id="t1", id=eid)
    assert fetched is not None
    assert fetched.name == "X"
    assert obj.id == eid


@pytest.mark.parametrize(
    ("type_svc_cls", "field_svc_cls", "parent_fk"),
    [
        (AssetTypeService, AssetTypeFieldService, "parent_id"),
        (MaintenanceRecordTypeService, MaintenanceRecordTypeFieldService, "parent_id"),
    ],
)
async def test_field_service_round_trip(
    type_svc_cls, field_svc_cls, parent_fk: str, session: AsyncSession,
) -> None:
    type_svc = type_svc_cls(session=session)
    field_svc = field_svc_cls(session=session)
    type_id = uuid4()
    field_id = uuid4()
    await type_svc.create(
        data={"tenant_id": "t1", "id": type_id, "name": "T", "active": True},
        auto_commit=False,
    )
    await session.flush()
    obj = await field_svc.create(
        data={
            "tenant_id": "t1",
            "id": field_id,
            parent_fk: type_id,
            "name": "f",
            "data_type": "text",
            "validation": None,
            "active": True,
        },
        auto_commit=False,
    )
    await session.flush()
    assert obj.id == field_id
    fetched = await field_svc.get_one_or_none(tenant_id="t1", id=field_id)
    assert fetched is not None
    assert getattr(fetched, parent_fk) == type_id
