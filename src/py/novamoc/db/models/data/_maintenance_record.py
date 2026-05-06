from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase, UUIDAuditBase
from advanced_alchemy.types import GUID, JsonB
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .._mixins import TenantScopedMixin


class MaintenanceRecord(TenantScopedMixin, UUIDAuditBase):
    """Maintenance record entity projection (ADR-005, ADR-012)."""

    __tablename__ = "maintenance_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["maintenance_record_types.tenant_id", "maintenance_record_types.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
        ),
    )

    type_id: Mapped[UUID] = mapped_column(GUID)
    asset_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str | None]
    properties: Mapped[dict[str, Any]] = mapped_column(
        JsonB, default=dict, server_default="{}"
    )
    deleted: Mapped[bool] = mapped_column(default=False, server_default="0")
    row_state_hlc: Mapped[str]


class MaintenanceRecordFieldValue(TenantScopedMixin, DefaultBase):
    """Per-field LWW projection for maintenance records (ADR-007, ADR-012)."""

    __tablename__ = "maintenance_record_field_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "maintenance_record_id"],
            ["maintenance_records.tenant_id", "maintenance_records.id"],
        ),
    )

    maintenance_record_id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    field_id: Mapped[str] = mapped_column(primary_key=True)
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    hlc: Mapped[str]
