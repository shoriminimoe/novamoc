from collections.abc import Sequence

import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.filters import OrderBy


class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetType]):
        model_type = m.schema.AssetType

    repository_type = Repo

    async def list_for_tenant(self, *, tenant_id: str) -> Sequence[m.schema.AssetType]:
        # ORDER BY id is load-bearing: the GET /schema endpoint emits a strong
        # ETag (RFC 7232 §2.3 byte-equality), so two responses for the same
        # schema_version must produce byte-identical bodies.
        return await self.list(
            m.schema.AssetType.tenant_id == tenant_id,
            OrderBy(field_name="id"),
        )
