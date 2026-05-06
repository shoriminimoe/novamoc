from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import GUID, JsonB
from sqlalchemy import Enum, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .._mixins import TenantScopedMixin
from ._types import FieldDataType


class AssetType(TenantScopedMixin, UUIDAuditBase):
    """User-defined asset type. Server-authoritative current state (ADR-008).

    ``active`` carries the lifecycle flag: a tombstoned row (``active = false``)
    stays in the table to keep its name reserved and to support resurrection.
    Name uniqueness applies across both states.
    """

    __tablename__ = "asset_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_asset_types_tenant_name"),
    )

    name: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="1")


class AssetTypeField(TenantScopedMixin, UUIDAuditBase):
    """User-defined field on an asset type. Server-authoritative current state."""

    __tablename__ = "asset_type_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["asset_types.tenant_id", "asset_types.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "parent_id",
            "name",
            name="uq_asset_type_fields_tenant_type_name",
        ),
    )

    parent_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str]
    data_type: Mapped[FieldDataType] = mapped_column(
        Enum(FieldDataType, native_enum=False)
    )
    validation: Mapped[dict[str, Any] | None] = mapped_column(JsonB)
    active: Mapped[bool] = mapped_column(default=True, server_default="1")
