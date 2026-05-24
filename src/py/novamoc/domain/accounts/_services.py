"""Account-domain services (ADR-020).

Thin advanced-alchemy wrappers; the registry tables are not
tenant-scoped, so callers do not pass a ``tenant_id`` and the storage
listeners short-circuit on column absence.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models._auth import Tenant, User

if TYPE_CHECKING:
    from advanced_alchemy.service import ModelDictT


def _fold_username(value: str) -> str:
    """NFKC-normalise and casefold a username.

    Ensures ``Admin`` and ``admin`` resolve to the same row
    (anti-impersonation, ADR-020).
    """
    return unicodedata.normalize("NFKC", value).casefold()


class TenantService(service.SQLAlchemyAsyncRepositoryService[Tenant]):
    class Repo(repository.SQLAlchemyAsyncRepository[Tenant]):
        model_type = Tenant

    repository_type = Repo


class UserService(service.SQLAlchemyAsyncRepositoryService[User]):
    """Service for the global user-account registry (ADR-020).

    Applies NFKC + ``casefold()`` to ``username`` at write time so
    ``Admin`` and ``admin`` always resolve to the same row.
    """

    class Repo(repository.SQLAlchemyAsyncRepository[User]):
        model_type = User

    repository_type = Repo

    async def create(self, data: ModelDictT[User] | User, **kwargs: Any) -> User:
        """Create a user, folding ``username`` before persisting."""
        if isinstance(data, dict):
            d: dict[str, Any] = data  # type: ignore  # ty can't narrow ModelDictT through isinstance
            raw = d.get("username")
            if isinstance(raw, str):
                data = {**d, "username": _fold_username(raw)}
        return await super().create(data, **kwargs)

    async def get_by_username(self, username: str) -> User | None:
        """Return the user whose folded username matches, or ``None``."""
        folded = _fold_username(username)
        return await self.get_one_or_none(username=folded)
