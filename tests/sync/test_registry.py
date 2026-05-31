from __future__ import annotations

import uuid

from novamoc.domain.sync._registry import NoopSubscriberRegistry


async def test_noop_registry_methods_are_no_ops() -> None:
    reg = NoopSubscriberRegistry()
    tid = uuid.uuid4()
    await reg.subscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.unsubscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"payload")
