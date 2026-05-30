"""Service-layer tests for ``TenantService`` (ADR-020).

Pins the helpers that the ``novamoc bootstrap-admin`` recipe (issue
#128) leans on to recover from partial failure — primarily
``get_by_display_name``, the lookup-or-create anchor for the
Development tenant.

Not tenant-scoped (the registry tables are not tenant-scoped), so the
autouse ``tenant`` fixture is skipped on every test in this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.domain.accounts._services import TenantService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.no_tenant


async def test_get_by_display_name_returns_none_when_absent(
    session: AsyncSession,
) -> None:
    svc = TenantService(session=session)
    assert await svc.get_by_display_name("Development") is None


async def test_get_by_display_name_returns_existing_tenant(
    session: AsyncSession,
) -> None:
    svc = TenantService(session=session)
    created = await svc.create(data={"display_name": "Development"}, auto_commit=False)
    await session.flush()

    found = await svc.get_by_display_name("Development")
    assert found is not None
    assert found.id == created.id


async def test_get_by_display_name_is_case_sensitive(session: AsyncSession) -> None:
    """``display_name`` is verbatim — no folding, unlike usernames.

    The bootstrap recipe always passes the same literal string, so a
    case-insensitive match here would risk collapsing distinct
    operator-created tenants.
    """
    svc = TenantService(session=session)
    await svc.create(data={"display_name": "Development"}, auto_commit=False)
    await session.flush()

    assert await svc.get_by_display_name("development") is None
    assert await svc.get_by_display_name("DEVELOPMENT") is None
