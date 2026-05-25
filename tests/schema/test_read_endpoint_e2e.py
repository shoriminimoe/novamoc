from __future__ import annotations


async def test_get_schema_empty_tenant_returns_zero_version_and_empty_lists(
    client,
) -> None:
    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "schema_version": 0,
        "asset_types": [],
        "maintenance_record_types": [],
    }


async def test_get_schema_returns_seeded_asset_type_with_field(
    client,
) -> None:
    seed_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "payload": {"name": "Truck-read-1"},
        },
    )
    assert seed_resp.status_code in (200, 201), seed_resp.text

    field_resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": "22222222-2222-2222-2222-222222222222",
            "payload": {
                "parent_id": "11111111-1111-1111-1111-111111111111",
                "name": "VIN",
                "data_type": "text",
            },
        },
    )
    assert field_resp.status_code in (200, 201), field_resp.text

    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] >= 2
    assert body["maintenance_record_types"] == []
    assert len(body["asset_types"]) == 1
    asset_type = body["asset_types"][0]
    assert asset_type["id"] == "11111111-1111-1111-1111-111111111111"
    assert asset_type["name"] == "Truck-read-1"
    assert asset_type["active"] is True
    assert len(asset_type["fields"]) == 1
    field = asset_type["fields"][0]
    assert field == {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "VIN",
        "data_type": "text",
        "validation": None,
        "active": True,
    }


async def test_get_schema_includes_tombstoned_rows(client) -> None:
    asset_type_id = "33333333-3333-3333-3333-333333333333"
    field_id = "44444444-4444-4444-4444-444444444444"

    create_t = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": asset_type_id,
            "payload": {"name": "Truck-tombstone"},
        },
    )
    assert create_t.status_code in (200, 201), create_t.text

    create_f = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": field_id,
            "payload": {
                "parent_id": asset_type_id,
                "name": "RetiredField",
                "data_type": "text",
            },
        },
    )
    assert create_f.status_code in (200, 201), create_f.text

    deactivate_f = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type_field",
            "entity_id": field_id,
            "payload": {},
        },
    )
    assert deactivate_f.status_code in (200, 201), deactivate_f.text

    deactivate_t = await client.post(
        "/schema",
        json={
            "type": "deactivate_asset_type",
            "entity_id": asset_type_id,
            "payload": {},
        },
    )
    assert deactivate_t.status_code in (200, 201), deactivate_t.text

    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    asset_types_by_id = {t["id"]: t for t in body["asset_types"]}
    truck = asset_types_by_id[asset_type_id]
    assert truck["active"] is False
    fields_by_id = {f["id"]: f for f in truck["fields"]}
    assert fields_by_id[field_id]["active"] is False


async def test_get_schema_without_session_returns_401(unauth_client) -> None:
    """Read endpoint goes through the same middleware as POST /schema."""
    resp = await unauth_client.get("/schema")
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"


async def test_get_schema_emits_etag_zero_for_empty_tenant(client) -> None:
    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == '"0"'


async def test_get_schema_emits_etag_matching_schema_version(client) -> None:
    create = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": "55555555-5555-5555-5555-555555555555",
            "payload": {"name": "Truck-etag"},
        },
    )
    assert create.status_code in (200, 201), create.text
    seq = create.json()["schema_version"]

    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == f'"{seq}"'
    assert resp.json()["schema_version"] == seq


async def test_if_none_match_matches_returns_304_with_etag_no_body(client) -> None:
    resp = await client.get("/schema", headers={"If-None-Match": '"0"'})
    assert resp.status_code == 304
    assert resp.headers["etag"] == '"0"'
    assert resp.content == b""


async def test_if_none_match_stale_returns_full_body_with_new_etag(client) -> None:
    create = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": "66666666-6666-6666-6666-666666666666",
            "payload": {"name": "Truck-304-stale"},
        },
    )
    assert create.status_code in (200, 201), create.text
    seq = create.json()["schema_version"]

    resp = await client.get("/schema", headers={"If-None-Match": '"0"'})
    assert resp.status_code == 200
    assert resp.headers["etag"] == f'"{seq}"'
    assert resp.json()["schema_version"] == seq


async def test_if_none_match_wildcard_returns_304(client) -> None:
    # RFC 7232 §3.2: If-None-Match: * matches when the server has any
    # current representation of the resource. For our endpoint, that's
    # always — even an empty tenant has a (zero-version, empty arrays)
    # representation. So `*` always wins.
    resp = await client.get("/schema", headers={"If-None-Match": "*"})
    assert resp.status_code == 304
    assert resp.headers["etag"] == '"0"'
    assert resp.content == b""


async def test_if_none_match_weak_etag_does_not_match_strong(client) -> None:
    # RFC 7232 §2.3.2 strong comparison: a weak inbound ETag never matches
    # the strong ETag we issue. Server returns 200 with the full body.
    resp = await client.get("/schema", headers={"If-None-Match": 'W/"0"'})
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"0"'


async def test_get_schema_orders_types_and_fields_deterministically(client) -> None:
    # Seed two asset types in reverse-id order; the response must order them
    # ascending by id (load-bearing for the strong ETag — see the
    # list_for_tenant docstrings on the projection services).
    type_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    type_c = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    field_a1 = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    field_a2 = "22222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    create_c = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_c,
            "payload": {"name": "Type-C"},
        },
    )
    assert create_c.status_code in (200, 201), create_c.text

    create_a = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_a,
            "payload": {"name": "Type-A"},
        },
    )
    assert create_a.status_code in (200, 201), create_a.text

    # Two fields on type_a, created in reverse-id order.
    create_a2 = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": field_a2,
            "payload": {
                "parent_id": type_a,
                "name": "Field-A2",
                "data_type": "text",
            },
        },
    )
    assert create_a2.status_code in (200, 201), create_a2.text

    create_a1 = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": field_a1,
            "payload": {
                "parent_id": type_a,
                "name": "Field-A1",
                "data_type": "text",
            },
        },
    )
    assert create_a1.status_code in (200, 201), create_a1.text

    resp = await client.get("/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Types ascend by id: aaaa... before cccc...
    type_ids = [t["id"] for t in body["asset_types"]]
    assert type_ids == [type_a, type_c]

    # Fields under type_a ascend by id: 1111... before 2222...
    field_ids = [f["id"] for f in body["asset_types"][0]["fields"]]
    assert field_ids == [field_a1, field_a2]

    # Two consecutive GETs return byte-identical bodies and the same ETag —
    # the strong-ETag invariant.
    second = await client.get("/schema")
    assert second.status_code == 200
    assert second.content == resp.content
    assert second.headers["etag"] == resp.headers["etag"]
