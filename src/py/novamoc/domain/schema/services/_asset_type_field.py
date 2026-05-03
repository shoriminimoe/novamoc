from collections.abc import Sequence

import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.filters import OrderBy


class AssetTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.AssetTypeField]
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetTypeField]):
        model_type = m.schema.AssetTypeField

    repository_type = Repo

    async def list_for_tenant(
        self, *, tenant_id: str
    ) -> Sequence[m.schema.AssetTypeField]:
        # ORDER BY (parent_id, id) groups fields under their parent type and
        # then orders deterministically within each parent. Required so the
        # GET /schema endpoint can issue a strong ETag (see AssetTypeService).
        return await self.list(
            m.schema.AssetTypeField.tenant_id == tenant_id,
            OrderBy(field_name="parent_id"),
            OrderBy(field_name="id"),
        )
