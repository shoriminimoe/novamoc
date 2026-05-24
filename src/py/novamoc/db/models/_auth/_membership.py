from __future__ import annotations

import uuid

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import GUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class UserTenantMembership(DefaultBase):
    """User ↔ tenant join table (ADR-020).

    Composite PK ``(user_id, tenant_id)`` doubles as the uniqueness
    constraint. ``DefaultBase`` (not ``UUIDAuditBase``) because the
    membership is a relation, not an entity — its identity is the pair,
    not an opaque id. No audit columns.

    The schema is N-to-N from day one so v2's switch-tenant feature is a
    service-layer relaxation, not a schema migration. v1's
    one-membership-per-user invariant is enforced at write time by
    :class:`~novamoc.domain.accounts._services.UserTenantMembershipService`.
    """

    __tablename__ = "user_tenant_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), primary_key=True
    )
    # ``info={"registry_fk": True}`` opts this column out of the
    # tenant-scoping listeners (``db/_listeners.py``): the value points
    # at a row in the ``tenants`` registry rather than declaring "this
    # row belongs to tenant X", which is what the listener's column-name
    # heuristic otherwise assumes.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenants.id"),
        primary_key=True,
        info={"registry_fk": True},
    )
