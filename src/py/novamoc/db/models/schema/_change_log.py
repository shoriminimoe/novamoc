from __future__ import annotations

import datetime as _dt
from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.types import GUID, DateTimeUTC, JsonB
from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column


class SchemaChangeLog(DefaultBase):
    """Append-only audit log of accepted schema commands (ADR-008).

    Command-grain — one row per accepted ``POST /schema``. Not folded
    into the schema projection; the projection is mutated transactionally
    alongside the append. The composite PK ``(tenant_id, seq)`` means
    each tenant has its own dense ``1, 2, 3, ...`` sequence — that
    per-tenant ``seq`` is the user/API-visible ``schema_version`` that
    ADR-009's catch-up flow walks. The next ``seq`` is computed at
    insert time (see ``SchemaChangeLogService.append``); SQLite has no
    per-partition identity.

    ``command`` is a plain ``TEXT`` column (not a DB enum). The valid
    vocabulary is :class:`novamoc.domain.schema._commands.SchemaCommand`;
    membership is enforced by the API request decoder, not the database,
    so adding new commands is a domain change rather than a migration.
    """

    __tablename__ = "schema_change_log"

    tenant_id: Mapped[str] = mapped_column(primary_key=True)
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
