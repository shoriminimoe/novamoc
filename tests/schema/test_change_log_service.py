from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models import schema as schema_models
from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def test_append_assigns_monotonic_seq(session: AsyncSession) -> None:
    svc = SchemaChangeLogService(session=session)
    a = await svc.append(
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "A"},
    )
    b = await svc.append(
        command=SchemaCommand.ACTIVATE_ASSET_TYPE,
        entity_id=uuid4(),
        payload={"name": "B"},
    )
    await session.flush()
    assert b.seq > a.seq

    rows = (
        (
            await session.execute(
                select(schema_models.SchemaChangeLog).order_by(
                    schema_models.SchemaChangeLog.seq
                )
            )
        )
        .scalars()
        .all()
    )
    assert [r.command for r in rows] == [
        SchemaCommand.ACTIVATE_ASSET_TYPE,
        SchemaCommand.ACTIVATE_ASSET_TYPE,
    ]


async def test_append_assigns_dense_per_tenant_seq(session: AsyncSession) -> None:
    """Each tenant gets its own ``1, 2, 3, ...`` sequence regardless of
    interleaving with other tenants (issue #17). Without this, a tenant's
    observable ``schema_version`` would skip values whenever a sibling
    tenant committed in between, leaking implementation noise into the
    protocol that ADR-009's catch-up flow consumes."""
    svc = SchemaChangeLogService(session=session)

    a, b = DEV_TENANT_ID_A, DEV_TENANT_ID_B
    interleaved: list[tuple[UUID, int]] = []
    # interleave A,B,A,B,A,B,A
    for tenant in (a, b, a, b, a, b, a):
        with use_tenant(tenant):
            row = await svc.append(
                command=SchemaCommand.CREATE_ASSET_TYPE,
                entity_id=uuid4(),
                payload={},
            )
            interleaved.append((tenant, row.seq))
    await session.flush()

    a_seqs = [seq for tenant, seq in interleaved if tenant == a]
    b_seqs = [seq for tenant, seq in interleaved if tenant == b]
    assert a_seqs == [1, 2, 3, 4]
    assert b_seqs == [1, 2, 3]
