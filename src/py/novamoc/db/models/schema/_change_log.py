from __future__ import annotations

import datetime as _dt
from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import GUID, DateTimeUTC, JsonB
from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from novamoc.db.models._mixins import TenantScopedMixin


class SchemaChangeLog(TenantScopedMixin, DefaultBase):
    """Append-only audit log of accepted schema commands (ADR-008).

    Composite PK ``(tenant_id, seq)`` — ``tenant_id`` from the mixin,
    ``seq`` declared here. Per-tenant dense ``1, 2, 3, …`` sequence;
    ``seq`` is application-managed (next_seq is computed at insert
    time in ``SchemaChangeLogService.append``), distinguishing this
    table from ``EventLog`` whose ``seq`` is DB-managed and globally
    monotonic.
    """

    __tablename__ = "schema_change_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    command: Mapped[str]
    entity_id: Mapped[UUID] = mapped_column(GUID)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB)
    committed_at: Mapped[_dt.datetime] = mapped_column(
        DateTimeUTC,
        server_default=func.now(),
        default=lambda: _dt.datetime.now(_dt.UTC),
    )
    actor_id: Mapped[str | None]
