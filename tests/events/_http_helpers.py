"""HTTP-layer seed helpers for ``/events`` e2e tests.

End-to-end tests for ``POST /events`` need referent ``asset_types`` /
``maintenance_record_types`` rows to satisfy the FK constraints on
the entity tables under ``PRAGMA foreign_keys=ON``. Rather than push
that boilerplate into every test, these helpers wrap the
``POST /schema`` calls each test pattern needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def create_asset_type(client: AsyncTestClient) -> tuple[str, int]:
    """Create an ``asset_type`` via ``POST /schema``.

    Returns ``(type_id, schema_version)``.
    """
    type_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_id,
            "payload": {"name": f"Truck-{type_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, int(resp.json()["schema_version"])


async def create_mr_type(client: AsyncTestClient) -> tuple[str, int]:
    """Create a ``maintenance_record_type`` via ``POST /schema``.

    Returns ``(type_id, schema_version)``.
    """
    type_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_maintenance_record_type",
            "entity_id": type_id,
            "payload": {"name": f"OilChange-{type_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, int(resp.json()["schema_version"])


async def create_asset(
    client: AsyncTestClient, *, type_id: str, schema_version: int, hlc: str
) -> str:
    """Create an asset row via ``POST /events`` so subsequent Updated /
    field-value events on that asset satisfy the FK into ``assets``.

    Returns the new asset's ``instance_id``. The caller supplies the
    ``hlc`` so it can sequence the seeding event before the events
    under test (HLCs must be strictly increasing within a tenant for
    LWW correctness, and the ``UNIQUE(tenant_id, hlc)`` constraint on
    ``event_log`` forbids reuse).
    """
    instance_id = str(uuid4())
    resp = await client.post(
        "/events",
        json={
            "schema_version": schema_version,
            "events": [
                {
                    "hlc": hlc,
                    "family": "asset",
                    "type_id": type_id,
                    "instance_id": instance_id,
                    "body": {"event": "created", "values": {}},
                }
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    return instance_id


__all__ = ("create_asset", "create_asset_type", "create_mr_type")
