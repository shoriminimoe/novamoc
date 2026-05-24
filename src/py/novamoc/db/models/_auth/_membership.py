from __future__ import annotations

import uuid

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import GUID
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class UserTenantMembership(DefaultBase):
    """User ↔ tenant join table (ADR-020).

    Composite PK ``(user_id, tenant_id)`` doubles as the uniqueness
    constraint on the pair. ``DefaultBase`` (not ``UUIDAuditBase``)
    because the membership is a relation, not an entity — its identity
    is the pair, not an opaque id. No audit columns.

    The table shape is N-to-N (column-wise) so v2's switch-tenant
    feature carries the same columns forward; the v1
    one-membership-per-user invariant is enforced both at the service
    layer (friendly :class:`UserAlreadyHasTenantError`) and
    structurally by ``UNIQUE(user_id)``, which v2 will drop as part of
    relaxing the invariant. Pre-release breaking changes are
    acceptable; a stronger v1 guarantee is worth a one-line v2
    migration.
    """

    __tablename__ = "user_tenant_memberships"
    __table_args__ = (
        # v1 invariant: at most one membership per user. v2 drops this
        # alongside the service-layer check that enforces the same rule.
        UniqueConstraint("user_id", name="uq_user_tenant_memberships_user_id"),
    )

    # ``ondelete="CASCADE"``: deleting a user account drops their
    # memberships (the join is meaningless without a user). ``RESTRICT``
    # on the tenant FK because tenant deletion is a sensitive admin
    # operation that should require explicit member cleanup. Both fire
    # only when ``PRAGMA foreign_keys=ON``; ADR-004 specifies it should
    # be on, production wiring is a separate follow-up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # ``info={"registry_fk": True}`` opts this column out of the
    # tenant-scoping listeners (``db/_listeners.py``): the value points
    # at a row in the ``tenants`` registry rather than declaring "this
    # row belongs to tenant X", which is what the listener's column-name
    # heuristic otherwise assumes.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
        info={"registry_fk": True},
    )
