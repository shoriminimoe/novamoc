"""End-to-end tests for ``GET /sync/initial`` (M2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_empty_tenant_returns_terminal_batch(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/sync/initial")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 0
    assert body["cursor"] is None
    assert body["event_log_cursor"] == 0
    # Empty tenant collapses to the last table's terminal batch
    # (intermediates are skipped server-side; the body's `table` tag
    # is incidental).
    assert body["body"]["table"] == "maintenance_record_field_values"
    assert body["body"]["items"] == []


async def test_post_event_then_get_sync_initial_round_trip(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())
    post = await client.post(
        "/events",
        json={
            "schema_version": 0,
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

    items_by_table: dict[str, list[dict]] = {}
    cursor: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "100"}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/sync/initial", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        table = body["body"]["table"]
        items_by_table.setdefault(table, []).extend(body["body"]["items"])
        if body["cursor"] is None:
            assert body["event_log_cursor"] >= 1
            break
        cursor = body["cursor"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    assert len(items_by_table.get("assets", [])) == 1
    asset = items_by_table["assets"][0]
    assert asset["id"] == instance_id
    assert asset["type_id"] == type_id
    assert asset["deleted"] is False
    assert "row_state_hlc" in asset

    fvs = items_by_table.get("asset_field_values", [])
    name_fv = next(
        (
            r
            for r in fvs
            if r["asset_id"] == instance_id and r["field_id"] == "col:name"
        ),
        None,
    )
    assert name_fv is not None, fvs
    assert name_fv["value_json"] == "Truck-1"
    assert name_fv["hlc"] == "0001700000000000-00000-abc"


async def test_multi_batch_round_trip(client: AsyncTestClient) -> None:
    type_id = str(uuid4())
    instance_ids = [str(uuid4()) for _ in range(5)]
    for i, iid in enumerate(instance_ids):
        post = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": f"00017000000000{i:02d}-00000-abc",
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": iid,
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert post.status_code == 202, post.text

    seen_asset_ids: set[str] = set()
    cursor: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "2"}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/sync/initial", params=params)
        body = resp.json()
        if body["body"]["table"] == "assets":
            for r in body["body"]["items"]:
                assert r["id"] not in seen_asset_ids, "duplicates across pages"
                seen_asset_ids.add(r["id"])
        if body["cursor"] is None:
            break
        cursor = body["cursor"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    assert seen_asset_ids == set(instance_ids)


async def test_mid_transfer_schema_version_advance_is_observable(
    client: AsyncTestClient,
) -> None:
    type_id = str(uuid4())
    for i in range(3):
        post = await client.post(
            "/events",
            json={
                "schema_version": 0,
                "events": [
                    {
                        "hlc": f"00017000000000{i:02d}-00000-abc",
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": str(uuid4()),
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert post.status_code == 202, post.text

    resp1 = await client.get("/sync/initial", params={"results_per_page": "1"})
    body1 = resp1.json()
    v1 = body1["schema_version"]
    assert body1["cursor"] is not None

    schema_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": str(uuid4()),
            "payload": {"name": f"Truck-{uuid4()}"},
        },
    )
    assert schema_resp.status_code in (200, 201), schema_resp.text

    resp2 = await client.get(
        "/sync/initial",
        params={"cursor": body1["cursor"], "results_per_page": "1"},
    )
    body2 = resp2.json()
    assert body2["schema_version"] > v1


async def test_bad_cursor_returns_problem_details(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/sync/initial", params={"cursor": "not-base64!@#"})
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert "invalid_payload_shape" in body["type"]


async def test_results_per_page_below_min_is_400(client: AsyncTestClient) -> None:
    resp = await client.get("/sync/initial", params={"results_per_page": "0"})
    assert resp.status_code == 400, resp.text


async def test_results_per_page_above_max_is_400(client: AsyncTestClient) -> None:
    resp = await client.get("/sync/initial", params={"results_per_page": "5001"})
    assert resp.status_code == 400, resp.text


async def test_tombstoned_assets_are_included(client: AsyncTestClient) -> None:
    type_id = str(uuid4())
    instance_id = str(uuid4())

    create = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000000-00000-aaa",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert create.status_code == 202, create.text

    deact = await client.post(
        "/events",
        json={
            "schema_version": 0,
            "events": [
                {
                    "hlc": "0001700000000001-00000-aaa",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "deactivated"},
                }
            ],
        },
    )
    assert deact.status_code == 202, deact.text

    seen_assets: list[dict] = []
    cursor: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "100"}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get("/sync/initial", params=params)).json()
        if body["body"]["table"] == "assets":
            seen_assets.extend(body["body"]["items"])
        if body["cursor"] is None:
            break
        cursor = body["cursor"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    target = next(a for a in seen_assets if a["id"] == instance_id)
    assert target["deleted"] is True
