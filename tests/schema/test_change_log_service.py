from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.db.models import schema as schema_models
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService


async def test_append_writes_a_row_and_returns_seq(session: AsyncSession) -> None:
    svc = SchemaChangeLogService(session=session)
    eid = uuid4()
    row = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=eid,
        payload={"name": "Truck"},
    )
    await session.flush()
    assert row.seq is not None
    assert row.tenant_id == "t1"
    assert row.command == SchemaCommand.ACTIVATE_ASSET_TYPE
    assert row.entity_id == eid
    assert row.payload == {"name": "Truck"}
    assert row.committed_at is not None


async def test_append_assigns_monotonic_seq(session: AsyncSession) -> None:
    svc = SchemaChangeLogService(session=session)
    a = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "A"},
    )
    b = await svc.append(
        tenant_id="t1",
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "B"},
    )
    await session.flush()
    assert b.seq > a.seq

    rows = (
        await session.execute(
            select(schema_models.SchemaChangeLog).order_by(schema_models.SchemaChangeLog.seq)
        )
    ).scalars().all()
    assert [r.command for r in rows] == [
        SchemaCommand.ACTIVATE_ASSET_TYPE,
        SchemaCommand.ACTIVATE_ASSET_TYPE,
    ]
