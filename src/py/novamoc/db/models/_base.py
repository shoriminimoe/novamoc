from __future__ import annotations

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy.orm import Mapped, mapped_column


class TenantScopedAuditBase(UUIDAuditBase):
    """Abstract base for tenant-scoped tables with UUID id and audit columns.

    Composite primary key is ``(tenant_id, id)`` per ADR-014. ``tenant_id``
    sorts before ``id`` (``UUIDPrimaryKey.id`` uses ``sort_order=-100``) so the
    PK's leading column — and therefore its implicit index — is ``tenant_id``.
    """

    __abstract__ = True

    tenant_id: Mapped[str] = mapped_column(primary_key=True, sort_order=-200)
