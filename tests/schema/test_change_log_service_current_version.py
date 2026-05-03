from __future__ import annotations

from uuid import uuid4

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService


async def test_current_version_returns_zero_for_empty_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    assert await svc.current_version(tenant_id="t1") == 0


async def test_current_version_returns_max_seq_for_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    for _ in range(3):
        await svc.append(
            tenant_id="t1",
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={},
        )
    await session.flush()

    version = await svc.current_version(tenant_id="t1")
    assert version == 3


async def test_current_version_is_per_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    await svc.append(
        tenant_id="t-other",
        command=SchemaCommand.CREATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={},
    )
    await session.flush()

    assert await svc.current_version(tenant_id="t1") == 0
