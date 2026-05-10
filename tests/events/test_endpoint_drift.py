"""End-to-end tests for HLC drift validation on ``POST /events``."""

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
    # Tight drift budget so the rejection path is reachable with a
    # plausible HLC. The default 60s would require an event > 1 min
    # ahead, which works at runtime but is fragile in test wall-clock
    # terms.
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


async def test_far_future_hlc_is_rejected_as_drift_exceeded(
    client: AsyncTestClient,
) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [_event(_FAR_FUTURE_HLC)]},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/hlc_drift_exceeded.html"
    assert body["title"] == "HLC drift exceeded"
    assert body["status"] == 400
    assert body["hlc"] == _FAR_FUTURE_HLC
    assert body["limit_seconds"] == 5.0
    assert body["drift_seconds"] > 5.0


async def test_malformed_hlc_is_rejected_as_invalid_payload_shape(
    client: AsyncTestClient,
) -> None:
    resp = await client.post(
        "/events",
        json={"schema_version": 0, "events": [_event("not-an-hlc")]},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_first_bad_event_rejects_whole_batch(
    client: AsyncTestClient,
) -> None:
    # Atomicity contract: even though persistence lands in later
    # milestones, the rejection path refuses a batch containing a bad
    # event rather than partial-accepting it.
    resp = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                _event(_PAST_HLC),
                _event(_FAR_FUTURE_HLC),
                _event(_PAST_HLC),
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["hlc"] == _FAR_FUTURE_HLC
