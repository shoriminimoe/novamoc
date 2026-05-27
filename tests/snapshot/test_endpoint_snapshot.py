"""End-to-end tests for ``GET /snapshot`` (M2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.events._http_helpers import create_asset_type

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_empty_tenant_returns_terminal_batch(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 0
    assert body["page"] is None
    assert body["cursor"] == 0
    # Empty tenant collapses to the last table's terminal batch
    # (intermediates are skipped server-side; the body's `table` tag
    # is incidental).
    assert body["body"]["table"] == "maintenance_record_field_values"
    assert body["body"]["items"] == []


async def test_post_event_then_get_snapshot_round_trip(
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

    items_by_table: dict[str, list[dict]] = {}
    page: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "100"}
        if page:
            params["page"] = page
        resp = await client.get("/snapshot", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        table = body["body"]["table"]
        items_by_table.setdefault(table, []).extend(body["body"]["items"])
        if body["page"] is None:
            assert body["cursor"] >= 1
            break
        page = body["page"]
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
    type_id, schema_version = await create_asset_type(client)
    instance_ids = [str(uuid4()) for _ in range(5)]
    for i, iid in enumerate(instance_ids):
        post = await client.post(
            "/events",
            json={
                "schema_version": schema_version,
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
    page: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "2"}
        if page:
            params["page"] = page
        resp = await client.get("/snapshot", params=params)
        body = resp.json()
        if body["body"]["table"] == "assets":
            for r in body["body"]["items"]:
                assert r["id"] not in seen_asset_ids, "duplicates across pages"
                seen_asset_ids.add(r["id"])
        if body["page"] is None:
            break
        page = body["page"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    assert seen_asset_ids == set(instance_ids)


async def test_mid_transfer_schema_version_advance_is_observable(
    client: AsyncTestClient,
) -> None:
    type_id, schema_version = await create_asset_type(client)
    for i in range(3):
        post = await client.post(
            "/events",
            json={
                "schema_version": schema_version,
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

    resp1 = await client.get("/snapshot", params={"results_per_page": "1"})
    body1 = resp1.json()
    v1 = body1["schema_version"]
    assert body1["page"] is not None

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
        "/snapshot",
        params={"page": body1["page"], "results_per_page": "1"},
    )
    body2 = resp2.json()
    assert body2["schema_version"] > v1


async def test_bad_page_returns_problem_details(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/snapshot", params={"page": "not-base64!@#"})
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert "invalid_payload_shape" in body["type"]


async def test_results_per_page_below_min_is_400(client: AsyncTestClient) -> None:
    resp = await client.get("/snapshot", params={"results_per_page": "0"})
    assert resp.status_code == 400, resp.text


async def test_results_per_page_above_max_is_400(client: AsyncTestClient) -> None:
    resp = await client.get("/snapshot", params={"results_per_page": "5001"})
    assert resp.status_code == 400, resp.text


async def test_snapshot_then_catchup_full_handshake(
    client: AsyncTestClient,
) -> None:
    """End-to-end client bootstrap: snapshot → catch-up handshake.

    The canonical fresh-client flow ADR-015 + ADR-013 prescribe:
    bulk-fetch the projection via ``GET /snapshot``, then start
    incremental sync from the seq the server captured at the *start*
    of that transfer (returned as ``cursor`` on the terminal batch,
    fed to ``GET /events?cursor=``).

    The correctness pin: events appended *after* the snapshot started
    but *before* it terminated must surface via catch-up — they're
    absent from the projection rows but present in ``event_log`` past
    the captured ``start_seq``. Events already reflected in the
    projection at ``start_seq`` must NOT be re-emitted by catch-up.
    """
    type_id, schema_version = await create_asset_type(client)

    # Event 1: appended before the snapshot starts. Its instance will
    # appear in the snapshot's projection rows; catch-up MUST NOT
    # re-emit it.
    pre_snapshot_id = str(uuid4())
    pre = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": "0001700000000001-00000-aaa",
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": pre_snapshot_id,
                    "body": {
                        "event": "created",
                        "values": {"col:name": "Pre-snapshot truck"},
                    },
                }
            ],
        },
    )
    assert pre.status_code == 202, pre.text

    # Drive the snapshot to its terminal batch.
    snapshot_assets: list[dict] = []
    terminal_body: dict | None = None
    page: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "100"}
        if page:
            params["page"] = page
        resp = await client.get("/snapshot", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["body"]["table"] == "assets":
            snapshot_assets.extend(body["body"]["items"])
        if body["page"] is None:
            terminal_body = body
            break
        page = body["page"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    assert terminal_body is not None
    # The pre-snapshot asset is in the projection; the snapshot's
    # terminal `cursor` is the seq captured at the start of transfer.
    snapshot_cursor: int = terminal_body["cursor"]
    assert any(a["id"] == pre_snapshot_id for a in snapshot_assets)

    # Events 2 + 3: appended AFTER the snapshot's start_seq is
    # captured. The projection rows the client just received don't
    # reflect these; catch-up MUST emit them.
    post_snapshot_ids = [str(uuid4()) for _ in range(2)]
    for i, iid in enumerate(post_snapshot_ids):
        hlc = f"00017000000000{i + 2:02d}-00000-bbb"
        resp = await client.post(
            "/events",
            json={
                "schema_version": schema_version,
                "events": [
                    {
                        "hlc": hlc,
                        "family": "asset",
                        "type_id": type_id,
                        "instance_id": iid,
                        "body": {"event": "created", "values": {}},
                    }
                ],
            },
        )
        assert resp.status_code == 202, resp.text

    # Drive incremental catch-up from the snapshot's cursor.
    catchup_events: list[dict] = []
    next_cursor: int | None = snapshot_cursor
    requests = 0
    while True:
        resp = await client.get(
            "/events",
            params={"cursor": str(next_cursor), "results_per_page": "100"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        catchup_events.extend(body["items"])
        if body["cursor"] is None:
            break
        next_cursor = body["cursor"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    # Catch-up returns exactly the two post-snapshot events; the
    # pre-snapshot one stays out (its effect was already in the
    # projection at start_seq).
    catchup_instance_ids = {e["instance_id"] for e in catchup_events}
    assert catchup_instance_ids == set(post_snapshot_ids)
    assert pre_snapshot_id not in catchup_instance_ids


async def test_tombstoned_assets_are_included(client: AsyncTestClient) -> None:
    type_id, schema_version = await create_asset_type(client)
    instance_id = str(uuid4())

    create = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
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
            "schema_version": schema_version,
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
    page: str | None = None
    requests = 0
    while True:
        params = {"results_per_page": "100"}
        if page:
            params["page"] = page
        body = (await client.get("/snapshot", params=params)).json()
        if body["body"]["table"] == "assets":
            seen_assets.extend(body["body"]["items"])
        if body["page"] is None:
            break
        page = body["page"]
        requests += 1
        assert requests < 20, "runaway-loop guard"

    target = next(a for a in seen_assets if a["id"] == instance_id)
    assert target["deleted"] is True
