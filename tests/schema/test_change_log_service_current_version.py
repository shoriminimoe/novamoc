from __future__ import annotations

from uuid import uuid4

from novamoc.db._tenant_context import use_tenant
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService
from tests._constants import DEV_TENANT_ID, DEV_TENANT_ID_A


async def test_current_version_returns_zero_for_empty_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    assert await svc.current_version() == 0


async def test_current_version_returns_max_seq_for_tenant(session) -> None:
    svc = SchemaChangeLogService(session=session)
    for _ in range(3):
        await svc.append(
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={},
        )
    await session.flush()

    version = await svc.current_version()
    assert version == 3


async def test_current_version_is_per_tenant(session) -> None:
    with use_tenant(DEV_TENANT_ID_A):
        svc = SchemaChangeLogService(session=session)
        await svc.append(
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={},
        )
        await session.flush()

    with use_tenant(DEV_TENANT_ID):
        assert await svc.current_version() == 0
