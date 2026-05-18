from __future__ import annotations

import msgspec
import pytest

from novamoc.domain.accounts import Principal


def test_principal_round_trips_through_json() -> None:
    principal = Principal(id="0192d4c8-1f3a-7c1a-9d4f-1a2b3c4d5e6f", username="alice")

    encoded = msgspec.json.encode(principal)
    decoded = msgspec.json.decode(encoded, type=Principal)

    assert decoded == principal


def test_principal_is_frozen() -> None:
    principal = Principal(id="0192d4c8-1f3a-7c1a-9d4f-1a2b3c4d5e6f", username="alice")

    with pytest.raises(AttributeError):
        principal.username = "bob"  # ty: ignore[invalid-assignment]
