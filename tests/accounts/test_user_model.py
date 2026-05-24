"""Smoke tests for the User model and UserService (ADR-020, M5.3).

The table is not tenant-scoped — these tests opt out of the autouse
``tenant`` fixture so the contextvar isn't set, mirroring how login
and membership tests will be wired.
"""
# ruff: noqa: RUF001  # fullwidth chars are intentional test data for NFKC-fold coverage

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from novamoc.db.models import _auth as auth_models
from novamoc.domain.accounts._services import UserService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.no_tenant
async def test_user_id_is_assigned_uuid_after_flush(session: AsyncSession) -> None:
    obj = auth_models.User(
        username="alice",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$hash",  # noqa: S106
    )
    session.add(obj)
    await session.flush()
    assert isinstance(obj.id, UUID)
    assert obj.username == "alice"
    assert obj.disabled_at is None


@pytest.mark.no_tenant
async def test_user_unique_username_constraint_raises(session: AsyncSession) -> None:
    obj1 = auth_models.User(username="bob", password_hash="hash1")  # noqa: S106
    obj2 = auth_models.User(username="bob", password_hash="hash2")  # noqa: S106
    session.add(obj1)
    session.add(obj2)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.no_tenant
async def test_user_service_create_folds_username(session: AsyncSession) -> None:
    svc = UserService(session=session)
    obj = await svc.create(
        data={"username": "Alice", "password_hash": "hash"},
        auto_commit=False,
    )
    await session.flush()
    assert obj.username == "alice"


@pytest.mark.no_tenant
async def test_user_service_create_folds_unicode_username(
    session: AsyncSession,
) -> None:
    svc = UserService(session=session)
    obj = await svc.create(
        data={"username": "ＡＤＭＩＮ", "password_hash": "hash"},
        auto_commit=False,
    )
    await session.flush()
    # NFKC normalises fullwidth chars to ASCII, casefold lowercases
    assert obj.username == "admin"


@pytest.mark.no_tenant
async def test_get_by_username_case_insensitive(session: AsyncSession) -> None:
    svc = UserService(session=session)
    await svc.create(
        data={"username": "Charlie", "password_hash": "hash"},
        auto_commit=False,
    )
    await session.flush()
    found = await svc.get_by_username("CHARLIE")
    assert found is not None
    assert found.username == "charlie"


@pytest.mark.no_tenant
async def test_get_by_username_returns_none_when_not_found(
    session: AsyncSession,
) -> None:
    svc = UserService(session=session)
    found = await svc.get_by_username("nonexistent")
    assert found is None
