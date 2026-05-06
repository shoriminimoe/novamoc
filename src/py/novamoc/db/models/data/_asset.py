from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.base import DefaultBase, UUIDAuditBase
from advanced_alchemy.types import GUID, JsonB
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .._mixins import TenantScopedMixin


class Asset(TenantScopedMixin, UUIDAuditBase):
    """Asset entity projection (ADR-005, ADR-012).

    Materialized current-state projection of the event log. ``properties`` holds
    user-defined field values; named columns hold ``col:`` field values.
    """

    __tablename__ = "assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["asset_types.tenant_id", "asset_types.id"],
        ),
    )

    type_id: Mapped[UUID] = mapped_column(GUID)
    name: Mapped[str | None]
    properties: Mapped[dict[str, Any]] = mapped_column(
        JsonB, default=dict, server_default="{}"
    )
    deleted: Mapped[bool] = mapped_column(default=False, server_default="0")
    row_state_hlc: Mapped[str]


class AssetFieldValue(TenantScopedMixin, DefaultBase):
    """Per-field LWW projection for assets (ADR-007, ADR-012).

    The fold unit. Each row carries the winning HLC for one ``(asset, field)``.
    Field id may be a user-field id or a ``col:<column>`` reserved id. Has no
    audit columns: ``hlc`` is the projection's ordering key, and rows are
    rebuildable from the event log.
    """

    __tablename__ = "asset_field_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    field_id: Mapped[str] = mapped_column(primary_key=True)
    value_json: Mapped[Any | None] = mapped_column(JsonB)
    hlc: Mapped[str]
