from __future__ import annotations

from datetime import datetime

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy.orm import Mapped, mapped_column


class User(UUIDv7AuditBase):
    """User account identity (ADR-020).

    PK is the inherited UUIDv7 from :class:`UUIDv7AuditBase`;
    ``username`` is mutable (rename support) — the stable identity is
    the surrogate UUID, not the login string.

    Not tenant-scoped — a user account is a global identity that links
    to one (eventually many) tenants via ``user_tenant_memberships``.
    Storage listeners short-circuit naturally because the table has no
    ``tenant_id`` column.

    ``username`` is stored case-folded (NFKC + ``casefold()``) by the
    service layer; never write raw user input directly to this column.

    ``disabled_at`` is a timestamp rather than a boolean — the moment of
    disable is recoverable without a separate audit row, and login fails
    closed when set (anti-enumeration 401, ADR-020).
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    disabled_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
