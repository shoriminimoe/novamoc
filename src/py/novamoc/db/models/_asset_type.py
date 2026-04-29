from advanced_alchemy.base import UUIDBase
from advanced_alchemy.mixins import UniqueMixin
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.elements import ColumnElement
from collections.abc import Hashable


class AssetType(UUIDBase, UniqueMixin):
    __tablename__ = "asset_types"

    tenant_id = Mapped[str]
    name = Mapped[str]

    @classmethod
    def unique_hash(cls, tenant_id: str, name: str) -> Hashable:
        return (tenant_id, name)

    @classmethod
    def unique_filter(cls, tenant_id: str, name: str) -> ColumnElement[bool]:
        return cls.tenant_id == tenant_id and cls.name == name
