from __future__ import annotations

from datetime import datetime

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(UUIDv7AuditBase):
    """Tenant registry row (ADR-020).

    PK is the inherited UUIDv7 from :class:`UUIDv7AuditBase`; its value
    is what every tenant-scoped table's ``tenant_id`` column references.
    Not tenant-scoped itself — rows in this table *are* the tenants, so
    no ``tenant_id`` column. Storage listeners (``db/_listeners.py``)
    short-circuit naturally because they key off column presence.

    ``disabled_at`` is the soft-disable flag (login fails closed when set
    via the anti-enumeration 401, ADR-020). It is left as
    ``Mapped[datetime | None]`` rather than a boolean so the moment of
    disable is recoverable without a separate audit row.
    """

    __tablename__ = "tenants"

    display_name: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
