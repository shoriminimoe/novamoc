from litestar.testing import AsyncTestClient

from novamoc.asgi import create_app


async def test_app_starts_and_post_schema_route_exists() -> None:
    app = create_app()
    async with AsyncTestClient(app) as client:
        # POST /schema with bad body should give us a structured error,
        # not a 404 — confirms the route is registered.
        resp = await client.post(
            "/schema/",
            json={
                "type": "do_a_barrel_roll",
                "tenant_id": "t1",
                "entity_id": "01958f3b-3b9f-7d3a-89aa-000000000001",
                "payload": {},
            },
        )
        # The route exists; an unknown command becomes 400 invalid_payload_shape via msgspec decode.
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["error"] == "invalid_request"
        assert body["code"] == "invalid_payload_shape"
