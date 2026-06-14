from __future__ import annotations

import uuid

from novamoc.db._tenant_context import use_tenant
from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events.services import EventLogService
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B


async def _insert(session, tenant_id) -> EventLog:
    row = EventLog(
        tenant_id=tenant_id,
        hlc=f"hlc-{uuid.uuid4()}",
        schema_version=1,
        table_name="assets",
        type_id=str(uuid.uuid4()),
        entity_id=str(uuid.uuid4()),
        op=EventOp.DELETE,
        value_json=None,
    )
    with use_tenant(tenant_id):
        session.add(row)
        await session.flush()
    return row


async def test_current_seq_all_tenants_is_global(session) -> None:
    await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    assert await svc.current_seq_all_tenants() == b.seq  # global max, latest insert


async def test_current_seq_all_tenants_zero_when_empty(session) -> None:
    svc = EventLogService(session=session)
    assert await svc.current_seq_all_tenants() == 0


async def test_list_after_all_tenants_crosses_tenants_in_seq_order(session) -> None:
    a = await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    rows = await svc.list_after_all_tenants(0, 10)
    assert [r.seq for r in rows] == [a.seq, b.seq]
    assert {r.tenant_id for r in rows} == {DEV_TENANT_ID_A, DEV_TENANT_ID_B}


async def test_list_after_all_tenants_respects_after_and_limit(session) -> None:
    a = await _insert(session, DEV_TENANT_ID_A)
    b = await _insert(session, DEV_TENANT_ID_B)
    svc = EventLogService(session=session)
    after_a = await svc.list_after_all_tenants(a.seq, 10)
    assert [r.seq for r in after_a] == [b.seq]
    capped = await svc.list_after_all_tenants(0, 1)
    assert [r.seq for r in capped] == [a.seq]
