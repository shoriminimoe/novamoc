"""HTTP-layer seed helpers for ``/events`` e2e tests.

End-to-end tests for ``POST /events`` need referent ``asset_types`` /
``maintenance_record_types`` rows to satisfy the FK constraints on
the entity tables under ``PRAGMA foreign_keys=ON``. Rather than push
that boilerplate into every test, these helpers wrap the
``POST /schema`` calls each test pattern needs.

``event_envelope`` builds the wire-shape ``EventEnvelope`` dict for
``POST /events`` requests. Callers fill in only the fields that matter
to the test under hand — the defaults are a minimal-valid asset
``created`` event so shape-agnostic tests (drift, idempotency, schema
version) don't have to spell the body out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Mapping

    from litestar.testing import AsyncTestClient


DEFAULT_HLC = "0000000000000001-00000-client-a"


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


async def seed_asset_type_with_field(
    client: AsyncTestClient, *, field_data_type: str = "text"
) -> tuple[str, str, int]:
    """Create an ``asset_type`` and one user field via ``POST /schema``.

    Returns ``(type_id, field_id, schema_version)``.
    """
    type_id = str(uuid4())
    field_id = str(uuid4())
    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type",
            "entity_id": type_id,
            "payload": {"name": f"Truck-{type_id[:8]}"},
        },
    )
    assert resp.status_code in (200, 201), resp.text

    resp = await client.post(
        "/schema",
        json={
            "type": "create_asset_type_field",
            "entity_id": field_id,
            "payload": {
                "parent_id": type_id,
                "name": "vin",
                "data_type": field_data_type,
            },
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return type_id, field_id, int(resp.json()["schema_version"])


def event_envelope(
    *,
    type_id: str | None = None,
    hlc: str = DEFAULT_HLC,
    instance_id: str | None = None,
    values: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Wire-shape ``EventEnvelope`` dict for ``POST /events`` request bodies.

    Builds a minimal-valid ``asset`` family ``created`` event. ``values``
    defaults to ``{"col:name": "x"}`` so shape-agnostic tests (drift,
    idempotency, schema version) need not spell the body out. Tests that
    target other families or event types build the dict inline.
    """
    return {
        "hlc": hlc,
        "family": "asset",
        "type_id": type_id or str(uuid4()),
        "instance_id": instance_id or str(uuid4()),
        "body": {
            "event": "created",
            "values": dict(values) if values is not None else {"col:name": "x"},
        },
    }


__all__ = (
    "DEFAULT_HLC",
    "create_asset",
    "create_asset_type",
    "create_mr_type",
    "event_envelope",
    "seed_asset_type_with_field",
)
