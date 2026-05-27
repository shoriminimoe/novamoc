"""Low-level seed helpers for tests that need referent type/entity rows.

Many event-layer tests start by writing rows that reference an
``asset_type`` or ``maintenance_record_type`` via foreign key. With
``PRAGMA foreign_keys=ON`` (set per-connection by
:mod:`novamoc.db._pragmas`), those FK references must resolve to a
real row. These helpers insert the minimum scaffolding via raw
``session.execute(insert(...))`` so a test can mint a ``type_id`` /
``asset_id`` and use it immediately.

Use the higher-level :func:`tests.data.loader.load_scenario` (via the
``seed`` fixture) when a test wants named fields and rich payloads;
these helpers are for the cases where the test only needs a parent
row to exist so the FK resolves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import insert

from novamoc.db._tenant_context import current_tenant_id
from novamoc.db.models.data import Asset, MaintenanceRecord
from novamoc.db.models.schema import AssetType, MaintenanceRecordType

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


_ANY_HLC = "0000000000000001-00000-client-a"


def _tenant() -> UUID:
    tid = current_tenant_id.get()
    if tid is None:
        msg = "seed helper called without an active tenant context"
        raise RuntimeError(msg)
    return tid


async def seed_asset_type(
    session: AsyncSession,
    *,
    type_id: UUID | None = None,
    name: str | None = None,
) -> UUID:
    """Insert a minimal ``asset_types`` row and return its id."""
    type_id = type_id or uuid4()
    name = name or f"AssetType-{type_id.hex[:8]}"
    await session.execute(
        insert(AssetType).values(
            tenant_id=_tenant(),
            id=type_id,
            name=name,
            active=True,
        )
    )
    return type_id


async def seed_mr_type(
    session: AsyncSession,
    *,
    type_id: UUID | None = None,
    name: str | None = None,
) -> UUID:
    """Insert a minimal ``maintenance_record_types`` row and return its id."""
    type_id = type_id or uuid4()
    name = name or f"MrType-{type_id.hex[:8]}"
    await session.execute(
        insert(MaintenanceRecordType).values(
            tenant_id=_tenant(),
            id=type_id,
            name=name,
            active=True,
        )
    )
    return type_id


async def seed_asset(
    session: AsyncSession,
    *,
    asset_id: UUID | None = None,
    type_id: UUID | None = None,
) -> UUID:
    """Insert an ``assets`` row (and its FK target ``asset_types`` row).

    Returns the inserted asset's id.
    """
    asset_id = asset_id or uuid4()
    type_id = type_id or await seed_asset_type(session)
    await session.execute(
        insert(Asset).values(
            tenant_id=_tenant(),
            id=asset_id,
            type_id=type_id,
            name=None,
            properties={},
            deleted=False,
            row_state_hlc=_ANY_HLC,
        )
    )
    return asset_id


async def seed_maintenance_record(
    session: AsyncSession,
    *,
    record_id: UUID | None = None,
    type_id: UUID | None = None,
    asset_id: UUID | None = None,
) -> UUID:
    """Insert a ``maintenance_records`` row (and its FK target rows).

    Returns the inserted record's id.
    """
    record_id = record_id or uuid4()
    type_id = type_id or await seed_mr_type(session)
    asset_id = asset_id or await seed_asset(session)
    await session.execute(
        insert(MaintenanceRecord).values(
            tenant_id=_tenant(),
            id=record_id,
            type_id=type_id,
            asset_id=asset_id,
            name=None,
            properties={},
            deleted=False,
            row_state_hlc=_ANY_HLC,
        )
    )
    return record_id


__all__ = (
    "seed_asset",
    "seed_asset_type",
    "seed_maintenance_record",
    "seed_mr_type",
)
