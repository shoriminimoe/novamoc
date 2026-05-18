"""Service-level tests for SchemaChangeLogService.list_changes_after."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from novamoc.domain.schema._commands import SchemaCommand
from novamoc.domain.schema.services import SchemaChangeLogService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(svc: SchemaChangeLogService, n: int) -> None:
    for i in range(n):
        await svc.append(
            command=SchemaCommand.CREATE_ASSET_TYPE,
            entity_id=uuid4(),
            payload={"name": f"name-{i}"},
        )


async def test_list_changes_after_returns_rows_above_since(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=2, limit=100)
    seqs = [r.seq for r in rows]
    assert seqs == [3, 4, 5]


async def test_list_changes_after_respects_limit(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=0, limit=2)
    seqs = [r.seq for r in rows]
    assert seqs == [1, 2]


async def test_list_changes_after_orders_by_seq_ascending(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 5)
    await session.flush()

    rows = await svc.list_changes_after(since=0, limit=100)
    seqs = [r.seq for r in rows]
    assert seqs == sorted(seqs)
    assert seqs == [1, 2, 3, 4, 5]


async def test_list_changes_after_since_at_or_above_max_returns_empty(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    await _seed(svc, 3)
    await session.flush()

    rows_at = await svc.list_changes_after(since=3, limit=100)
    rows_above = await svc.list_changes_after(since=99, limit=100)
    assert list(rows_at) == []
    assert list(rows_above) == []


async def test_list_changes_after_empty_tenant_returns_empty(
    session: AsyncSession,
) -> None:
    svc = SchemaChangeLogService(session=session)
    rows = await svc.list_changes_after(since=0, limit=100)
    assert list(rows) == []
