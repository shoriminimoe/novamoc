from __future__ import annotations

import asyncio
import contextlib
import uuid

import msgspec
from advanced_alchemy.base import metadata_registry

from novamoc.db._tenant_context import use_tenant
from novamoc.db.config import build_alchemy_config
from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events._broadcaster import EventBroadcaster
from novamoc.domain.events._payloads import RecordedEvent
from tests._constants import DEV_TENANT_ID_A, DEV_TENANT_ID_B


class _StubRegistry:
    def __init__(self) -> None:
        self.published: list[tuple[uuid.UUID, bytes]] = []

    async def subscribe(self, tenant_id, socket) -> None: ...
    async def unsubscribe(self, tenant_id, socket) -> None: ...
    async def publish(self, tenant_id: uuid.UUID, message: bytes) -> None:
        self.published.append((tenant_id, message))


async def _make_config(settings):
    cfg = build_alchemy_config(settings)
    engine = cfg.get_engine()
    async with engine.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    return cfg


async def _insert(cfg, tenant_id) -> int:
    async with cfg.get_session() as session:
        with use_tenant(tenant_id):
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
            session.add(row)
            await session.flush()
            seq = row.seq
            await session.commit()
    return seq


async def test_drain_delivers_each_row_to_its_tenant(settings) -> None:
    cfg = await _make_config(settings)
    seq_a = await _insert(cfg, DEV_TENANT_ID_A)
    await _insert(cfg, DEV_TENANT_ID_B)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)

    drained = await bcast.drain_once()

    assert drained == 2
    assert [t for t, _ in reg.published] == [DEV_TENANT_ID_A, DEV_TENANT_ID_B]
    first = msgspec.json.decode(reg.published[0][1], type=RecordedEvent)
    assert first.seq == seq_a
    assert await bcast.drain_once() == 0
    await cfg.get_engine().dispose()


async def test_start_at_tip_skips_existing_then_delivers_new(settings) -> None:
    cfg = await _make_config(settings)
    await _insert(cfg, DEV_TENANT_ID_A)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)

    await bcast.start_at_tip()
    assert await bcast.drain_once() == 0

    await _insert(cfg, DEV_TENANT_ID_B)
    assert await bcast.drain_once() == 1
    assert reg.published[0][0] == DEV_TENANT_ID_B
    await cfg.get_engine().dispose()


async def test_drain_respects_batch_size(settings) -> None:
    cfg = await _make_config(settings)
    await _insert(cfg, DEV_TENANT_ID_A)
    await _insert(cfg, DEV_TENANT_ID_A)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=1)

    assert await bcast.drain_once() == 1
    assert await bcast.drain_once() == 1
    assert await bcast.drain_once() == 0
    await cfg.get_engine().dispose()


async def test_run_loop_drains_on_signal(settings) -> None:
    cfg = await _make_config(settings)
    reg = _StubRegistry()
    bcast = EventBroadcaster(reg, cfg, batch_size=500)
    task = asyncio.create_task(bcast.run())
    try:
        await _insert(cfg, DEV_TENANT_ID_A)
        bcast.notify()
        for _ in range(200):  # bounded wait
            if reg.published:
                break
            await asyncio.sleep(0.01)
        assert len(reg.published) == 1
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await cfg.get_engine().dispose()
