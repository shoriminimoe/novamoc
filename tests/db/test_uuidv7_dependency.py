"""Tests that advanced-alchemy produces real UUIDv7 PKs (issue #126).

advanced-alchemy's ``UUIDv7Base`` (and the ``UUIDv7PrimaryKey`` mixin it
inherits from) defers UUID v7 generation to the optional ``uuid-utils``
package. When ``uuid-utils`` is not installed it falls back to ``uuid4``
and logs a warning — silently violating ADR-020's UUIDv7 commitment for
the ``sessions`` registry table, which uses ``UUIDv7Base`` via
``SessionModelMixin``.

The fix is to declare ``uuid-utils`` in ``[project].dependencies`` so the
real ``uuid7`` generator is always available. This test pins that
contract: the ``Session`` model's ``id`` PK must be a UUIDv7.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest

from novamoc.db.models._auth._session import Session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.no_tenant
async def test_session_pk_is_uuidv7(session: AsyncSession) -> None:
    """``Session.id`` is a UUIDv7 — proves ``uuid-utils`` is installed.

    Without ``uuid-utils``, advanced-alchemy substitutes ``uuid4`` for
    ``uuid7`` and the generated PK has ``version == 4``. With the
    dependency installed, ``UUIDv7Base``'s default callable produces a
    real UUIDv7 (``version == 7``).
    """
    row = Session(
        session_id="test-session",
        data=b"",
        expires_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(row)
    await session.flush()
    assert row.id.version == 7, (
        f"Expected UUIDv7 for sessions.id; got version {row.id.version}. "
        "Is `uuid-utils` installed?"
    )
