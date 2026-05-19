"""Unit tests for the opaque sync cursor."""

from __future__ import annotations

import base64
import json

import pytest

from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.sync._cursor import (
    CursorState,
    InitialSyncTable,
    decode_cursor,
    encode_cursor,
)


@pytest.mark.parametrize(
    ("table", "last_id"),
    [
        (InitialSyncTable.ASSETS, None),
        (InitialSyncTable.ASSETS, "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f"),
        (InitialSyncTable.ASSET_FIELD_VALUES, None),
        (
            InitialSyncTable.ASSET_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:col:name",
        ),
        (InitialSyncTable.MAINTENANCE_RECORDS, None),
        (
            InitialSyncTable.MAINTENANCE_RECORD_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:f0a1b2c3-d4e5-6789-abcd-ef0123456789",
        ),
    ],
)
def test_cursor_roundtrip(table: InitialSyncTable, last_id: str | None) -> None:
    state = CursorState(start_seq=17, table=table, last_id=last_id)
    encoded = encode_cursor(state)
    assert isinstance(encoded, str)
    decoded = decode_cursor(encoded)
    assert decoded == state


def test_cursor_decode_rejects_garbage() -> None:
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor("not-base64!@#")
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_non_json_base64() -> None:
    token = base64.urlsafe_b64encode(b"\x00\x01\x02").rstrip(b"=").decode()
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_missing_fields() -> None:
    token = (
        base64.urlsafe_b64encode(json.dumps({"start_seq": 1}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_rejects_unknown_table() -> None:
    token = (
        base64.urlsafe_b64encode(
            json.dumps({"start_seq": 1, "table": "users", "last_id": None}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(PayloadShapeError) as exc:
        decode_cursor(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_cursor_decode_accepts_padded_token() -> None:
    """Be liberal in what we accept: padded base64 from naive clients."""
    state = CursorState(start_seq=42, table=InitialSyncTable.ASSETS, last_id=None)
    encoded = encode_cursor(state)
    padded = encoded + "=" * (-len(encoded) % 4)
    assert decode_cursor(padded) == state
