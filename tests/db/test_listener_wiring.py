"""The listeners must be active for the conftest's session/engine fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novamoc.db._errors import UnscopedQueryError
from novamoc.db.models.schema._asset_type import AssetType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.no_tenant
async def test_session_fixture_has_listeners_active(session: AsyncSession) -> None:
    """Without the contextvar, even the session fixture rejects flushes."""
    session.add(AssetType(name="Truck", active=True))
    with pytest.raises(UnscopedQueryError):
        await session.flush()
