from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from litestar.exceptions import WebSocketException

from novamoc.domain.sync._registry import InMemorySubscriberRegistry

if TYPE_CHECKING:
    from collections.abc import Callable


class _FakeSocket:
    """Records send_data calls; optionally fails to simulate a dead peer.

    May run an on_send hook to exercise mid-publish mutation.
    """

    def __init__(
        self, *, fail: bool = False, on_send: Callable[[], None] | None = None
    ) -> None:
        self.sent: list[bytes] = []
        self._fail = fail
        self._on_send = on_send

    async def send_data(self, data: bytes, mode: str = "text") -> None:
        if self._on_send is not None:
            self._on_send()
        if self._fail:
            raise WebSocketException(detail="boom")
        self.sent.append(data)


async def test_publish_delivers_to_subscriber() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    sock = _FakeSocket()
    await reg.subscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"hello")
    assert sock.sent == [b"hello"]


async def test_publish_reaches_all_subscribers_of_a_tenant() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    a, b = _FakeSocket(), _FakeSocket()
    await reg.subscribe(tid, a)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid, b)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")
    assert a.sent == [b"x"]
    assert b.sent == [b"x"]


async def test_publish_is_tenant_scoped() -> None:
    reg = InMemorySubscriberRegistry()
    tid_a, tid_b = uuid.uuid4(), uuid.uuid4()
    a, b = _FakeSocket(), _FakeSocket()
    await reg.subscribe(tid_a, a)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid_b, b)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid_a, b"only-a")
    assert a.sent == [b"only-a"]
    assert b.sent == []


async def test_unsubscribe_stops_delivery_and_prunes() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    sock = _FakeSocket()
    await reg.subscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.unsubscribe(tid, sock)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")
    assert sock.sent == []
    assert tid not in reg._subscribers


async def test_publish_suppresses_a_dead_socket() -> None:
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    dead, alive = _FakeSocket(fail=True), _FakeSocket()
    await reg.subscribe(tid, dead)  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid, alive)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")  # must not raise
    assert alive.sent == [b"x"]


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    reg = InMemorySubscriberRegistry()
    await reg.publish(uuid.uuid4(), b"x")  # must not raise


async def test_unsubscribe_unknown_tenant_is_a_noop() -> None:
    reg = InMemorySubscriberRegistry()
    sock = _FakeSocket()
    # Must not raise.
    await reg.unsubscribe(uuid.uuid4(), sock)  # ty: ignore[invalid-argument-type]


async def test_publish_iterates_a_snapshot() -> None:
    # A socket that subscribes a new peer mid-send must not trip a
    # "set changed during iteration" error — publish iterates a copy.
    reg = InMemorySubscriberRegistry()
    tid = uuid.uuid4()
    late = _FakeSocket()
    first = _FakeSocket(on_send=lambda: reg._subscribers[tid].add(late))  # ty: ignore[invalid-argument-type]
    await reg.subscribe(tid, first)  # ty: ignore[invalid-argument-type]
    await reg.publish(tid, b"x")  # must not raise
    assert first.sent == [b"x"]
    # The late subscriber joined after the snapshot, so it misses this batch.
    assert late.sent == []
