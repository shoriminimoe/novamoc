"""``RecordedEvent`` round-trips encode → decode unchanged."""

from __future__ import annotations

import datetime as _dt
from uuid import uuid4

import msgspec
import pytest

from novamoc.db.models.data import EventLog, EventOp
from novamoc.domain.events._bundle import _FAMILY_BY_TABLE_NAME, body_from_row
from novamoc.domain.events._payloads import (
    Activated,
    Created,
    Deactivated,
    EntityFamily,
    RecordedEvent,
    Updated,
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


def _row(op: EventOp, value_json: dict[str, object] | None) -> EventLog:
    return EventLog(
        seq=1,
        tenant_id="t",
        hlc="0001700000000000-00000-abc",
        schema_version=0,
        table_name="assets",
        type_id=str(uuid4()),
        entity_id=str(uuid4()),
        field_id=None,
        op=op,
        value_json=value_json,
        received_at=_dt.datetime(2026, 5, 18, 12, 0, tzinfo=_dt.UTC),
    )


def test_body_from_row_created() -> None:
    row = _row(EventOp.SET, {"event": "created", "values": {"col:name": "T-1"}})
    assert body_from_row(row) == Created(values={"col:name": "T-1"})


def test_body_from_row_updated() -> None:
    row = _row(EventOp.SET, {"event": "updated", "values": {"col:name": "T-2"}})
    assert body_from_row(row) == Updated(values={"col:name": "T-2"})


def test_body_from_row_activated() -> None:
    row = _row(EventOp.SET, {"event": "activated"})
    assert body_from_row(row) == Activated()


def test_body_from_row_deactivated_uses_op_not_value_json() -> None:
    row = _row(EventOp.DELETE, None)
    assert body_from_row(row) == Deactivated()


@pytest.mark.parametrize(
    ("table_name", "family"),
    [
        ("assets", EntityFamily.ASSET),
        ("maintenance_records", EntityFamily.MAINTENANCE_RECORD),
    ],
)
def test_family_by_table_name_inverse_of_table_names(
    table_name: str, family: EntityFamily
) -> None:
    assert _FAMILY_BY_TABLE_NAME[table_name] is family
