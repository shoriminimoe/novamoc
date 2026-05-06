from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import GUID, JsonB
from sqlalchemy import Enum, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .._mixins import TenantScopedMixin
from ._types import FieldDataType


class MaintenanceRecordType(TenantScopedMixin, UUIDAuditBase):
    """User-defined maintenance record type. Server-authoritative current state."""

    __tablename__ = "maintenance_record_types"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_maintenance_record_types_tenant_name"
        ),
    )

    name: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="1")


class MaintenanceRecordTypeField(TenantScopedMixin, UUIDAuditBase):
    """User-defined field on a maintenance record type. Server-authoritative current state."""

    __tablename__ = "maintenance_record_type_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["maintenance_record_types.tenant_id", "maintenance_record_types.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "parent_id",
            "name",
            name="uq_maintenance_record_type_fields_tenant_type_name",
        ),
    )

    parent_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str]
    data_type: Mapped[FieldDataType] = mapped_column(
        Enum(FieldDataType, native_enum=False)
    )
    validation: Mapped[dict[str, Any] | None] = mapped_column(JsonB)
    active: Mapped[bool] = mapped_column(default=True, server_default="1")
