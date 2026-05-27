"""``GET /events`` catch-up endpoint (M2.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.events._http_helpers import create_asset_type

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_get_events_empty_stream_returns_no_items(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["cursor"] is None
    assert body["results_per_page"] == 500


async def test_get_events_returns_appended_events(
    client: AsyncTestClient,
) -> None:
    type_id, schema_version = await create_asset_type(client)
    instance_id = str(uuid4())
    post = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": "0001700000000000-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {
                        "event": "created",
                        "values": {"col:name": "Truck-1"},
                    },
                }
            ],
        },
    )
    assert post.status_code == 202, post.text

    resp = await client.get("/events/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The asset_type's POST /schema is also an event_log row? No —
    # schema commands write to ``schema_change_log``, not ``event_log``.
    # The /events catch-up reflects only the data Created event.
    assert len(body["items"]) == 1
    event = body["items"][0]
    assert event["hlc"] == "0001700000000000-00000-abc"
    assert event["family"] == "asset"
    assert event["type_id"] == type_id
    assert event["instance_id"] == instance_id
    assert event["body"] == {
        "event": "created",
        "parent": None,
        "values": {"col:name": "Truck-1"},
    }
    assert event["seq"] > 0
    assert event["schema_version"] == schema_version
    assert "received_at" in event
    assert body["cursor"] is None


async def test_get_events_paginates_via_cursor(
    client: AsyncTestClient,
) -> None:
    type_id, schema_version = await create_asset_type(client)

    async def post_one(i: int) -> None:
        hlc = f"00017000000000{i:02d}-00000-abc"
        resp = await client.post(
            "/events",
            json={
                "schema_version": schema_version,
                "events": [
                    {
                        "hlc": hlc,
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": str(uuid4()),
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert resp.status_code == 202, resp.text

    for i in range(5):
        await post_one(i)

    resp1 = await client.get("/events/?results_per_page=2")
    body1 = resp1.json()
    assert len(body1["items"]) == 2
    assert body1["cursor"] is not None

    resp2 = await client.get(f"/events/?cursor={body1['cursor']}&results_per_page=2")
    body2 = resp2.json()
    assert len(body2["items"]) == 2
    assert body2["cursor"] is not None

    resp3 = await client.get(f"/events/?cursor={body2['cursor']}&results_per_page=2")
    body3 = resp3.json()
    assert len(body3["items"]) == 1
    assert body3["cursor"] is None

    all_seqs = [it["seq"] for it in body1["items"] + body2["items"] + body3["items"]]
    assert all_seqs == sorted(all_seqs)
    assert len(set(all_seqs)) == 5


async def test_get_events_body_round_trip_all_variants(
    client: AsyncTestClient,
) -> None:
    type_id, schema_version = await create_asset_type(client)
    instance_id = str(uuid4())

    posts = [
        {
            "hlc": "0001700000000001-00000-abc",
            "body": {
                "event": "created",
                "values": {"col:name": "X"},
                "parent": None,
            },
        },
        {
            "hlc": "0001700000000002-00000-abc",
            "body": {"event": "updated", "values": {"col:name": "Y"}},
        },
        {
            "hlc": "0001700000000003-00000-abc",
            "body": {"event": "deactivated"},
        },
        {
            "hlc": "0001700000000004-00000-abc",
            "body": {"event": "activated"},
        },
    ]
    for p in posts:
        resp = await client.post(
            "/events",
            json={
                "schema_version": schema_version,
                "events": [
                    {
                        "hlc": p["hlc"],
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": instance_id,
                        "body": p["body"],
                    }
                ],
            },
        )
        assert resp.status_code == 202, resp.text

    resp = await client.get("/events/")
    items = resp.json()["items"]
    assert len(items) == 4
    by_hlc = {it["hlc"]: it for it in items}
    for p in posts:
        assert by_hlc[p["hlc"]]["body"] == p["body"]


async def test_get_events_preserves_acceptance_time_schema_version(
    client: AsyncTestClient,
) -> None:
    # Seed an asset_type — FKs on the assets projection require a real
    # referent — and capture the schema_version the event is accepted under.
    type_id, schema_version_at_accept = await create_asset_type(client)
    post1 = await client.post(
        "/events",
        json={
            "schema_version": schema_version_at_accept,
            "events": [
                {
                    "hlc": "0001700000000001-00000-abc",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": str(uuid4()),
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert post1.status_code == 202, post1.text

    # Advance the schema (create another asset_type) -> schema_version increments.
    schema_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(uuid4()),
            "payload": {"name": f"Truck-{uuid4().hex[:8]}"},
        },
    )
    assert schema_resp.status_code in (200, 201), schema_resp.text

    # The recorded event still carries the version it was accepted under.
    resp = await client.get("/events/")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["schema_version"] == schema_version_at_accept


async def test_get_events_rejects_negative_cursor(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?cursor=-1")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_get_events_rejects_zero_results_per_page(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?results_per_page=0")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_get_events_rejects_oversized_results_per_page(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/events/?results_per_page=5001")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
