from collections.abc import Sequence

from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.filters import OrderBy

import novamoc.db.models as m


class MaintenanceRecordTypeService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordType],
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordType]):
        model_type = m.schema.MaintenanceRecordType

    repository_type = Repo

    async def list_for_tenant(
        self, *, tenant_id: str
    ) -> Sequence[m.schema.MaintenanceRecordType]:
        # ORDER BY id is load-bearing for the GET /schema strong-ETag contract
        # (see AssetTypeService).
        return await self.list(
            m.schema.MaintenanceRecordType.tenant_id == tenant_id,
            OrderBy(field_name="id"),
        )
