"""``RecordedEvent`` round-trips encode → decode unchanged."""

from __future__ import annotations

import datetime as _dt
from uuid import uuid4

import msgspec

from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    RecordedEvent,
)


def test_recorded_event_encode_decode_round_trip() -> None:
    original = RecordedEvent(
        seq=42,
        schema_version=7,
        hlc="0001700000000000-00000-abc",
        family=EntityFamily.ASSET,
        type_id=uuid4(),
        instance_id=uuid4(),
        body=Created(values={"col:name": "Truck-1"}),
        received_at=_dt.datetime(2026, 5, 18, 12, 0, tzinfo=_dt.UTC),
    )
    wire = msgspec.json.encode(original)
    round_tripped = msgspec.json.decode(wire, type=RecordedEvent)
    assert round_tripped == original
