"""Unit tests for the public validator surface (M1.4 reshape)."""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID, uuid4

import pytest

from novamoc.db.models.schema._types import FieldDataType
from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.events._errors import UnknownFieldError, ValueTypeMismatchError
from novamoc.domain.events._payloads import (
    Created,
    EntityFamily,
    EventEnvelope,
    Updated,
)
from novamoc.domain.events._validators import (
    json_type_name,
    matches_data_type,
    validate_values,
)


@dataclasses.dataclass
class _FieldRow:
    """Stand-in for AssetTypeField / MaintenanceRecordTypeField in unit tests.

    The validator only reads ``data_type`` (and ``active`` is ignored — tombstoned
    fields are still accepted). ``id`` is kept so the row matches the public
    field shape; the handler is now responsible for tenant/type scoping.
    """

    id: UUID
    data_type: FieldDataType
    active: bool = True


_TYPE_ID = UUID("11111111-1111-1111-1111-111111111111")


def _event(family: EntityFamily = EntityFamily.ASSET) -> EventEnvelope:
    return EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=family,
        type_id=_TYPE_ID,
        instance_id=uuid4(),
        body=Created(values={}),
    )


def _values(values: dict[str, Any]) -> None:
    """Drive validate_values against ``_TYPE_ID`` with one user field of TEXT."""
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {field_id: _FieldRow(id=field_id, data_type=FieldDataType.TEXT)}
    validate_values(event=_event(), values=values, fields_by_id=fields_by_id)


# --- json_type_name -----------------------------------------------------------


def test_json_type_name_distinguishes_bool_from_int() -> None:
    assert json_type_name(True) == "boolean"
    assert json_type_name(1) == "integer"


def test_json_type_name_null() -> None:
    assert json_type_name(None) == "null"


def test_json_type_name_string() -> None:
    assert json_type_name("x") == "string"


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (None, "null"),
        (True, "boolean"),
        (False, "boolean"),
        (1, "integer"),
        (1.5, "number"),
        ("x", "string"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_json_type_name_matrix(value: Any, label: str) -> None:
    assert json_type_name(value) == label


# --- matches_data_type --------------------------------------------------------


def test_matches_null_against_any_type() -> None:
    for dt in FieldDataType:
        assert matches_data_type(None, dt) is True


def test_matches_integer_rejects_bool() -> None:
    assert matches_data_type(True, FieldDataType.INTEGER) is False


def test_matches_number_rejects_bool() -> None:
    assert matches_data_type(False, FieldDataType.NUMBER) is False


def test_matches_text_rejects_int() -> None:
    assert matches_data_type(1, FieldDataType.TEXT) is False


@pytest.mark.parametrize(
    ("value", "data_type", "expected"),
    [
        # TEXT
        ("hello", FieldDataType.TEXT, True),
        (42, FieldDataType.TEXT, False),
        # NUMBER
        (1.5, FieldDataType.NUMBER, True),
        (1, FieldDataType.NUMBER, True),
        ("1.5", FieldDataType.NUMBER, False),
        # INTEGER
        (7, FieldDataType.INTEGER, True),
        (7.5, FieldDataType.INTEGER, False),
        # BOOLEAN
        (True, FieldDataType.BOOLEAN, True),
        (False, FieldDataType.BOOLEAN, True),
        (1, FieldDataType.BOOLEAN, False),
        # DATE — ISO 8601 strings; deeper format validation is deferred.
        ("2026-05-11", FieldDataType.DATE, True),
        (20260511, FieldDataType.DATE, False),
        # DATETIME — same shape rule as DATE for now.
        ("2026-05-11T12:00:00Z", FieldDataType.DATETIME, True),
        (1.0, FieldDataType.DATETIME, False),
    ],
)
def test_matches_data_type_matrix(
    value: Any, data_type: FieldDataType, expected: bool
) -> None:
    assert matches_data_type(value, data_type) is expected


# --- validate_values: user-field keys ----------------------------------------


def test_valid_user_field_accepted() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    _values({str(field_id): "ok"})


def test_unknown_user_field_raises_unknown_field() -> None:
    with pytest.raises(UnknownFieldError) as exc:
        _values({str(uuid4()): "x"})
    assert exc.value.extras["family"] == "asset"
    assert exc.value.extras["type_id"] == str(_TYPE_ID)


def test_wrong_user_field_type_raises_value_type_mismatch() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    with pytest.raises(ValueTypeMismatchError) as exc:
        _values({str(field_id): 42})
    assert exc.value.extras == {
        "field": str(field_id),
        "expected": "text",
        "received": "integer",
    }


def test_tombstoned_user_field_still_accepted() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {
        field_id: _FieldRow(id=field_id, data_type=FieldDataType.TEXT, active=False)
    }
    validate_values(
        event=_event(), values={str(field_id): "still works"}, fields_by_id=fields_by_id
    )


def test_non_uuid_non_col_key_raises_payload_shape_error() -> None:
    with pytest.raises(PayloadShapeError) as exc:
        _values({"not-a-uuid": "x"})
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE
    assert exc.value.extras["field"] == "not-a-uuid"


# --- validate_values: col: keys ----------------------------------------------


def test_user_writable_col_name_accepts_text() -> None:
    validate_values(event=_event(), values={"col:name": "Truck-7"}, fields_by_id={})


def test_user_writable_col_name_rejects_int() -> None:
    with pytest.raises(ValueTypeMismatchError) as exc:
        validate_values(event=_event(), values={"col:name": 1}, fields_by_id={})
    assert exc.value.extras["expected"] == "text"
    assert exc.value.extras["received"] == "integer"


def test_unknown_col_raises_unknown_field() -> None:
    with pytest.raises(UnknownFieldError) as exc:
        validate_values(event=_event(), values={"col:bogus": "x"}, fields_by_id={})
    assert exc.value.extras["field"] == "col:bogus"


@pytest.mark.parametrize(
    "reserved", ["col:type_id", "col:asset_id", "col:deleted", "col:row_state_hlc"]
)
def test_reserved_col_raises_payload_shape_error(reserved: str) -> None:
    with pytest.raises(PayloadShapeError) as exc:
        validate_values(event=_event(), values={reserved: "x"}, fields_by_id={})
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE
    assert exc.value.extras["field"] == reserved


# --- validate_values: empty / Updated bodies ---------------------------------


def test_empty_values_dict_is_noop() -> None:
    validate_values(event=_event(), values={}, fields_by_id={})


def test_updated_event_with_null_clears_cell() -> None:
    field_id = UUID("22222222-2222-2222-2222-222222222222")
    fields_by_id = {field_id: _FieldRow(id=field_id, data_type=FieldDataType.INTEGER)}
    body = Updated(values={str(field_id): None})
    event = EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=EntityFamily.ASSET,
        type_id=_TYPE_ID,
        instance_id=uuid4(),
        body=body,
    )
    validate_values(event=event, values=body.values, fields_by_id=fields_by_id)
