"""End-to-end tests for HLC drift on ``POST /events`` (M1.2 + M1.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from novamoc.config import (
    AppSettings,
    DatabaseSettings,
    ServerSettings,
    Settings,
)

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


_PAST_HLC = "0000000000000001-00000-client-a"
_FAR_FUTURE_HLC = "9999999999999999-00000-client-a"


def _event(hlc: str) -> dict[str, object]:
    return {
        "hlc": hlc,
        "family": "asset",
        "type_id": str(uuid4()),
        "instance_id": str(uuid4()),
        "body": {"event": "created", "values": {"col:name": "x"}},
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:///:memory:",
            static_pool=True,
            create_all=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test", hlc_drift_limit_seconds=5.0),
    )


async def test_past_hlc_is_accepted(client: AsyncTestClient) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [_event(_PAST_HLC)]},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["outcomes"] == [{"hlc": _PAST_HLC, "outcome": "accepted"}]


async def test_far_future_hlc_yields_rejected_outcome(
    client: AsyncTestClient,
) -> None:
    # Per M1.5 drift is now a per-event reject, not a batch 4xx; the
    # batch HTTP envelope still returns 202.
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [_event(_FAR_FUTURE_HLC)]},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["outcomes"] == [
        {"hlc": _FAR_FUTURE_HLC, "outcome": "rejected:hlc_drift_exceeded"}
    ]


async def test_malformed_hlc_yields_rejected_invalid_payload_shape(
    client: AsyncTestClient,
) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [_event("not-an-hlc")]},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["outcomes"] == [
        {"hlc": "not-an-hlc", "outcome": "rejected:invalid_payload_shape"}
    ]


async def test_mixed_batch_records_each_event_independently(
    client: AsyncTestClient,
) -> None:
    # A drift-exceeded event does NOT poison its neighbours (M1.5
    # acceptance criteria): accepted events still apply.
    resp = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                _event(_PAST_HLC),
                _event(_FAR_FUTURE_HLC),
                _event("0000000000000002-00000-client-a"),
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    outcomes = resp.json()["outcomes"]
    assert [o["outcome"] for o in outcomes] == [
        "accepted",
        "rejected:hlc_drift_exceeded",
        "accepted",
    ]
