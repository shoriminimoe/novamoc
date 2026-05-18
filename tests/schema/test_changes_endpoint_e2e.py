"""E2E HTTP tests for GET /schema/changes (issue #32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient

_TYPE_A = "11111111-1111-1111-1111-111111111111"
_TYPE_B = "22222222-2222-2222-2222-222222222222"
_TYPE_C = "33333333-3333-3333-3333-333333333333"


async def _seed_three_creates(client: AsyncTestClient) -> None:
    for eid, name in ((_TYPE_A, "A"), (_TYPE_B, "B"), (_TYPE_C, "C")):
        resp = await client.post(
            "/schema",
            json={
                "type": "create_asset_type",
                "entity_id": eid,
                "payload": {"name": name},
            },
        )
        assert resp.status_code in (200, 201), resp.text


async def test_empty_tenant_returns_empty_changes(client) -> None:
    resp = await client.get("/schema/changes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "schema_version": 0,
        "changes": [],
        "next_since": 0,
        "has_more": False,
    }


async def test_since_zero_returns_full_history(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] == 3
    assert body["next_since"] == 3
    assert body["has_more"] is False
    seqs = [c["seq"] for c in body["changes"]]
    assert seqs == [1, 2, 3]
    commands = [c["command"] for c in body["changes"]]
    assert commands == ["create_asset_type"] * 3


async def test_since_at_current_returns_empty_not_error(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=3")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 3
    assert body["changes"] == []
    assert body["next_since"] == 3
    assert body["has_more"] is False


async def test_since_above_current_returns_empty_not_error(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=999")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 3
    assert body["changes"] == []
    # next_since echoes the input when no rows are returned, so a client
    # that keeps calling with the same cursor doesn't go backwards.
    assert body["next_since"] == 999
    assert body["has_more"] is False


async def test_since_skips_rows_below_or_equal(client) -> None:
    await _seed_three_creates(client)

    resp = await client.get("/schema/changes?since=1")
    assert resp.status_code == 200
    body = resp.json()
    seqs = [c["seq"] for c in body["changes"]]
    # Exclusive lower bound: seq > 1, so [2, 3].
    assert seqs == [2, 3]
    assert body["next_since"] == 3
    assert body["has_more"] is False


async def test_limit_pages_results(client) -> None:
    await _seed_three_creates(client)

    page1 = await client.get("/schema/changes?since=0&limit=2")
    assert page1.status_code == 200
    body1 = page1.json()
    assert [c["seq"] for c in body1["changes"]] == [1, 2]
    assert body1["next_since"] == 2
    assert body1["has_more"] is True

    page2 = await client.get(f"/schema/changes?since={body1['next_since']}&limit=2")
    assert page2.status_code == 200
    body2 = page2.json()
    assert [c["seq"] for c in body2["changes"]] == [3]
    assert body2["next_since"] == 3
    assert body2["has_more"] is False


async def test_row_carries_payload_and_actor_id_null(client) -> None:
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": _TYPE_A,
            "payload": {"name": "Truck"},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "payload": {
                "parent_id": _TYPE_A,
                "name": "VIN",
                "data_type": "text",
            },
        },
    )

    resp = await client.get("/schema/changes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["changes"]) == 2

    create_type, create_field = body["changes"]
    assert create_type["command"] == "create_asset_type"
    assert create_type["entity_id"] == _TYPE_A
    assert create_type["payload"] == {"name": "Truck"}
    assert create_type["actor_id"] is None
    assert isinstance(create_type["committed_at"], str)
    assert "T" in create_type["committed_at"]  # ISO-8601-ish

    assert create_field["command"] == "create_asset_type_field"
    assert create_field["payload"] == {
        "parent_id": _TYPE_A,
        "name": "VIN",
        "data_type": "text",
    }


async def test_deactivate_and_activate_surface_as_separate_rows(client) -> None:
    await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": _TYPE_A,
            "payload": {"name": "Truck"},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "entity_id": _TYPE_A,
            "payload": {},
        },
    )
    await client.post(
        "/schema",
        json={
            "type": "activate_asset_type",
            "entity_id": _TYPE_A,
            "payload": {},
        },
    )

    resp = await client.get("/schema/changes")
    body = resp.json()
    commands = [c["command"] for c in body["changes"]]
    assert commands == [
        "create_asset_type",
        "deactivate_asset_type",
        "activate_asset_type",
    ]


async def test_since_negative_returns_400(client) -> None:
    resp = await client.get("/schema/changes?since=-1")
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_limit_zero_returns_400(client) -> None:
    resp = await client.get("/schema/changes?limit=0")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_limit_above_max_returns_400(client) -> None:
    # Default max is 500; pick something definitively above.
    resp = await client.get("/schema/changes?limit=1000000")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_non_integer_query_returns_400(client) -> None:
    resp = await client.get("/schema/changes?since=abc")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["type"].endswith("/invalid_payload_shape.html")


async def test_without_authorization_returns_401(client) -> None:
    resp = await client.get("/schema/changes", headers={"Authorization": ""})
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"
