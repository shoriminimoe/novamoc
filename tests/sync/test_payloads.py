from __future__ import annotations

import uuid

import msgspec
import pytest

from novamoc.domain.sync._payloads import Hello, Pong, Welcome


def test_hello_decodes_with_type_tag() -> None:
    tid = uuid.uuid4()
    raw = msgspec.json.encode(
        {"type": "hello", "tenant_id": str(tid), "cursor": 7}
    )
    hello = msgspec.json.decode(raw, type=Hello)
    assert hello.tenant_id == tid
    assert hello.cursor == 7


def test_hello_rejects_unknown_field() -> None:
    raw = msgspec.json.encode(
        {"type": "hello", "tenant_id": str(uuid.uuid4()), "cursor": 0, "x": 1}
    )
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(raw, type=Hello)


def test_hello_rejects_wrong_tag() -> None:
    raw = msgspec.json.encode(
        {"type": "welcome", "tenant_id": str(uuid.uuid4()), "cursor": 0}
    )
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(raw, type=Hello)


def test_welcome_encodes_with_type_tag() -> None:
    encoded = msgspec.json.encode(Welcome(server_seq=3, schema_version=4))
    assert msgspec.json.decode(encoded) == {
        "type": "welcome",
        "server_seq": 3,
        "schema_version": 4,
    }


def test_pong_encodes_bare_tag() -> None:
    assert msgspec.json.decode(msgspec.json.encode(Pong())) == {"type": "pong"}
