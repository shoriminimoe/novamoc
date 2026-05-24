"""Account-domain services (ADR-020).

Thin advanced-alchemy wrappers; the registry tables are not
tenant-scoped, so callers do not pass a ``tenant_id`` and the storage
listeners short-circuit on column absence.
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import TYPE_CHECKING, Any

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models._auth import Tenant, User, UserTenantMembership
from novamoc.domain.accounts._errors import UserAlreadyHasTenantError

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


class UserTenantMembershipService(
    service.SQLAlchemyAsyncRepositoryService[UserTenantMembership]
):
    """Service for the user ↔ tenant join table (ADR-020).

    Enforces the v1 one-membership-per-user invariant at write time —
    :meth:`create` raises :class:`UserAlreadyHasTenantError` if the
    target ``user_id`` already holds a membership. The schema itself is
    N-to-N so v2's switch-tenant feature relaxes only this service-layer
    check.
    """

    class Repo(repository.SQLAlchemyAsyncRepository[UserTenantMembership]):
        model_type = UserTenantMembership

    repository_type = Repo

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserTenantMembership]:
        """Return every membership row for ``user_id`` (empty if none)."""
        return list(await self.list(user_id=user_id))

    async def get_for_user(self, user_id: uuid.UUID) -> UserTenantMembership | None:
        """Return the membership row for ``user_id`` or ``None``.

        The 1:1 invariant guarantees at most one row, so callers do not
        need to count. v2 will relax this to a ``list_for_user`` call at
        the call site.
        """
        return await self.get_one_or_none(user_id=user_id)

    async def create(
        self,
        data: ModelDictT[UserTenantMembership] | UserTenantMembership,
        **kwargs: Any,
    ) -> UserTenantMembership:
        """Create a membership, enforcing the 1:1 invariant.

        Two layers of enforcement:

        * Pre-check: extract ``user_id`` from ``data`` and raise the
          friendly :class:`UserAlreadyHasTenantError` if a membership
          already exists. Covers the common shapes (dict, ORM
          instance, anything exposing a ``user_id`` attribute).
        * Backstop: the ``UNIQUE(user_id)`` constraint on
          :class:`UserTenantMembership` rejects any insert the
          pre-check missed (concurrent inserts, exotic payload shapes)
          with :class:`~sqlalchemy.exc.IntegrityError`. Callers that
          need the friendly error for those paths must catch the
          IntegrityError themselves.

        Raises:
            UserAlreadyHasTenantError: ``user_id`` already has a
                membership row (pre-check path).
        """
        user_id = _extract_user_id(data)
        if user_id is not None and await self.list_for_user(user_id):
            raise UserAlreadyHasTenantError
        return await super().create(data, **kwargs)


def _extract_user_id(
    data: ModelDictT[UserTenantMembership] | UserTenantMembership,
) -> uuid.UUID | None:
    """Best-effort ``user_id`` extraction from a create payload.

    Covers the shapes ``ModelDictT`` actually admits today: ``dict``,
    ORM instance, and any object exposing a ``user_id`` attribute
    (msgspec Structs, pydantic models, attrs classes, dataclasses).
    Accepts UUID or string-form (``GUID.process_bind_param`` admits
    both, so the DB sees the same value either way). A ``None`` return
    means "could not extract" — the service-layer pre-check is skipped
    and the ``UniqueConstraint("user_id")`` on the model is the
    backstop.
    """
    if isinstance(data, dict):
        d: dict[str, Any] = data  # type: ignore  # ty can't narrow ModelDictT through isinstance
        value: object = d.get("user_id")
    else:
        value = getattr(data, "user_id", None)
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None
