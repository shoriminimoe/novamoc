"""Unit tests for the opaque snapshot page token."""

from __future__ import annotations

import base64
import json

import pytest

from novamoc.domain._errors import ErrorCode, PayloadShapeError
from novamoc.domain.snapshot._page import (
    PageState,
    SnapshotTable,
    decode_page,
    encode_page,
)


@pytest.mark.parametrize(
    ("table", "last_id"),
    [
        (SnapshotTable.ASSETS, None),
        (SnapshotTable.ASSETS, "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f"),
        (SnapshotTable.ASSET_FIELD_VALUES, None),
        (
            SnapshotTable.ASSET_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:col:name",
        ),
        (SnapshotTable.MAINTENANCE_RECORDS, None),
        (
            SnapshotTable.MAINTENANCE_RECORD_FIELD_VALUES,
            "8c1d0a2f-7b3e-4c5a-9d6e-1a2b3c4d5e6f:f0a1b2c3-d4e5-6789-abcd-ef0123456789",
        ),
    ],
)
def test_page_roundtrip(table: SnapshotTable, last_id: str | None) -> None:
    state = PageState(start_seq=17, table=table, last_id=last_id)
    encoded = encode_page(state)
    assert isinstance(encoded, str)
    decoded = decode_page(encoded)
    assert decoded == state


def test_page_decode_rejects_garbage() -> None:
    with pytest.raises(PayloadShapeError) as exc:
        decode_page("not-base64!@#")
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_page_decode_rejects_non_json_base64() -> None:
    token = base64.urlsafe_b64encode(b"\x00\x01\x02").rstrip(b"=").decode()
    with pytest.raises(PayloadShapeError) as exc:
        decode_page(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_page_decode_rejects_missing_fields() -> None:
    token = (
        base64.urlsafe_b64encode(json.dumps({"start_seq": 1}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(PayloadShapeError) as exc:
        decode_page(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_page_decode_rejects_unknown_table() -> None:
    token = (
        base64.urlsafe_b64encode(
            json.dumps({"start_seq": 1, "table": "users", "last_id": None}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(PayloadShapeError) as exc:
        decode_page(token)
    assert exc.value.code is ErrorCode.INVALID_PAYLOAD_SHAPE


def test_page_decode_accepts_padded_token() -> None:
    """Be liberal in what we accept: padded base64 from naive clients."""
    state = PageState(start_seq=42, table=SnapshotTable.ASSETS, last_id=None)
    encoded = encode_page(state)
    padded = encoded + "=" * (-len(encoded) % 4)
    assert decode_page(padded) == state
