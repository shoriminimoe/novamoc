"""Smoke tests for the Tenant registry model (ADR-020, M5.2).

The table is not tenant-scoped — these tests opt out of the autouse
``tenant`` fixture so the contextvar isn't set, mirroring how the M5.4+
membership / login tests will be wired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from novamoc.db.models import _auth as auth_models
from novamoc.domain.accounts._services import TenantService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.no_tenant
async def test_tenant_id_is_assigned_uuid_after_flush(session: AsyncSession) -> None:
    obj = auth_models.Tenant(display_name="Development")
    session.add(obj)
    await session.flush()
    assert isinstance(obj.id, UUID)
    assert obj.display_name == "Development"
    assert obj.disabled_at is None


@pytest.mark.no_tenant
async def test_tenant_service_create_returns_model_with_uuid_id(
    session: AsyncSession,
) -> None:
    svc = TenantService(session=session)
    obj = await svc.create(data={"display_name": "X"}, auto_commit=False)
    await session.flush()
    assert isinstance(obj.id, UUID)
    assert obj.display_name == "X"


@pytest.mark.no_tenant
async def test_tenant_disabled_at_round_trips(session: AsyncSession) -> None:
    moment = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    svc = TenantService(session=session)
    obj = await svc.create(
        data={"display_name": "Y", "disabled_at": moment},
        auto_commit=False,
    )
    await session.flush()
    assert obj.disabled_at == moment
