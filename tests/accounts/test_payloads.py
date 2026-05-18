from __future__ import annotations

import msgspec
import pytest
from msgspec_ext import SecretStr

from novamoc.domain.accounts._payloads import (
    LoginRequest,
    MePrincipal,
    MeResponse,
    MeTenant,
    decode_hook,
)


def test_login_request_decodes_clean_payload() -> None:
    wire = b'{"username": "alice", "password": "hunter2"}'

    decoded = msgspec.json.decode(wire, type=LoginRequest, dec_hook=decode_hook)

    assert decoded.username == "alice"
    assert isinstance(decoded.password, SecretStr)
    assert decoded.password.get_secret_value() == "hunter2"


def test_login_request_password_is_masked_in_repr() -> None:
    wire = b'{"username": "alice", "password": "hunter2"}'

    decoded = msgspec.json.decode(wire, type=LoginRequest, dec_hook=decode_hook)

    assert "hunter2" not in repr(decoded)
    assert "**********" in repr(decoded)


def test_login_request_rejects_unknown_field() -> None:
    wire = b'{"username": "alice", "password": "hunter2", "extra": "nope"}'

    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(wire, type=LoginRequest, dec_hook=decode_hook)


def test_me_response_round_trips_through_json() -> None:
    response = MeResponse(
        user=MePrincipal(id="0192d4c8-1f3a-7c1a-9d4f-1a2b3c4d5e6f", username="alice"),
        tenant=MeTenant(
            id="0192d4c8-2222-7c1a-9d4f-1a2b3c4d5e6f",
            display_name="Acme Maintenance",
        ),
    )

    encoded = msgspec.json.encode(response)
    decoded = msgspec.json.decode(encoded, type=MeResponse)

    assert decoded == response
