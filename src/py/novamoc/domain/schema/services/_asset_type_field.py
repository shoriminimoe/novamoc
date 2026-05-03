from collections.abc import Sequence

import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.AssetTypeField]
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetTypeField]):
        model_type = m.schema.AssetTypeField

    repository_type = Repo

    async def list_for_tenant(
        self, *, tenant_id: str
    ) -> Sequence[m.schema.AssetTypeField]:
        return await self.list(m.schema.AssetTypeField.tenant_id == tenant_id)
