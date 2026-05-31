from __future__ import annotations

import uuid

from novamoc.domain.sync._registry import (
    NoopSubscriberRegistry,
    SubscriberRegistry,
)


async def test_noop_registry_methods_are_callable() -> None:
    reg = NoopSubscriberRegistry()
    tid = uuid.uuid4()
    # No socket object needed — the no-op ignores it.
    await reg.subscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.unsubscribe(tid, object())  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"payload")


def test_noop_satisfies_protocol() -> None:
    reg: SubscriberRegistry = NoopSubscriberRegistry()
    assert isinstance(reg, SubscriberRegistry)
