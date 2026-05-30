"""Tests that advanced-alchemy produces real UUIDv7 PKs (issue #126).

advanced-alchemy's ``UUIDv7Base`` (and the ``UUIDv7PrimaryKey`` mixin it
inherits from) defers UUID v7 generation to the optional ``uuid-utils``
package. When ``uuid-utils`` is not installed it falls back to ``uuid4``
and logs a warning — silently violating ADR-020's UUIDv7 commitment for
the ``sessions`` registry table, which uses ``UUIDv7Base`` via
``SessionModelMixin``.

The fix is twofold:

1. Declare ``uuid-utils`` in ``[project].dependencies`` so the real
   ``uuid7`` generator is always available. This is pinned by
   :func:`test_session_pk_is_uuidv7`.
2. Switch the ``Tenant`` and ``User`` registry models to
   :class:`UUIDv7AuditBase` so their PKs actually honour ADR-020 line 46
   ("Tenant ids become UUIDv7"). Pinned by
   :func:`test_tenant_pk_is_uuidv7` and :func:`test_user_pk_is_uuidv7`.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest

from novamoc.db.models._auth._session import Session
from novamoc.db.models._auth._tenant import Tenant
from novamoc.db.models._auth._user import User

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


@pytest.mark.no_tenant
async def test_tenant_pk_is_uuidv7(session: AsyncSession) -> None:
    """``Tenant.id`` is a UUIDv7 — pins ADR-020 line 46.

    The docstring on :class:`Tenant` advertises a UUIDv7 PK, and
    ADR-020 mandates it explicitly. The base class must therefore be
    :class:`UUIDv7AuditBase` (not :class:`UUIDAuditBase`, whose
    ``default_factory`` produces ``uuid4``).
    """
    row = Tenant(display_name="probe")
    session.add(row)
    await session.flush()
    assert row.id.version == 7, (
        f"Expected UUIDv7 for tenants.id; got version {row.id.version}. "
        "Is `Tenant` inheriting from `UUIDv7AuditBase`?"
    )


@pytest.mark.no_tenant
async def test_user_pk_is_uuidv7(session: AsyncSession) -> None:
    """``User.id`` is a UUIDv7 — pins ADR-020 line 46.

    The docstring on :class:`User` advertises a UUIDv7 PK, and ADR-020
    mandates it explicitly. The base class must therefore be
    :class:`UUIDv7AuditBase` (not :class:`UUIDAuditBase`, whose
    ``default_factory`` produces ``uuid4``).
    """
    row = User(username="probe", password_hash="hash")  # noqa: S106
    session.add(row)
    await session.flush()
    assert row.id.version == 7, (
        f"Expected UUIDv7 for users.id; got version {row.id.version}. "
        "Is `User` inheriting from `UUIDv7AuditBase`?"
    )
