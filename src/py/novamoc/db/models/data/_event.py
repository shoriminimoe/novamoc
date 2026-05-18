from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import GUID, BigIntIdentity, DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Enum, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column


class EventOp(StrEnum):
    """EAV-grain event operation for the data event log."""

    SET = "set"
    DELETE = "delete"


class EventLog(DefaultBase):
    """Append-only data event log (ADR-002, ADR-011).

    Source of truth for all synchronized data. ``seq`` is globally monotonic;
    per-tenant streaming uses ``(tenant_id, seq)``. ``UNIQUE(tenant_id, hlc)``
    enforces idempotent re-delivery. Not derived from ``BigIntAuditBase``
    because ADR-011 mandates the column be named ``seq``, not ``id``;
    ``received_at`` serves the audit role for an append-only log.
    """

    __tablename__ = "event_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "hlc", name="uq_event_log_tenant_hlc"),
        Index("idx_event_log_tenant_seq", "tenant_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(
        BigIntIdentity, primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[UUID] = mapped_column(GUID)
    hlc: Mapped[str]
    schema_version: Mapped[int] = mapped_column(BigInteger)
    table_name: Mapped[str]
    type_id: Mapped[str]
    entity_id: Mapped[str]
    field_id: Mapped[str | None]
    op: Mapped[EventOp] = mapped_column(Enum(EventOp, native_enum=False))
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    received_at: Mapped[datetime] = mapped_column(
        DateTimeUTC, server_default=func.now()
    )
