"""Smoke tests for the Session model (ADR-020, M5.7).

The table is not tenant-scoped — these tests opt out of the autouse
``tenant`` fixture so the contextvar isn't set, mirroring the tenant
model tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from novamoc.db.models import _auth as auth_models

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.no_tenant
async def test_session_id_is_assigned_uuid_after_flush(session: AsyncSession) -> None:
    obj = auth_models.Session(
        session_id="abc123",
        data=b"opaque",
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    session.add(obj)
    await session.flush()
    assert isinstance(obj.id, UUID)


@pytest.mark.no_tenant
async def test_session_fields_round_trip(session: AsyncSession) -> None:
    expires = datetime(2030, 6, 15, 12, 0, tzinfo=UTC)
    obj = auth_models.Session(
        session_id="roundtrip-token",
        data=b"opaque",
        expires_at=expires,
    )
    session.add(obj)
    await session.flush()

    obj_id = obj.id
    await session.refresh(obj)

    assert obj.id == obj_id
    assert obj.session_id == "roundtrip-token"
    assert obj.data == b"opaque"
    assert obj.expires_at == expires
