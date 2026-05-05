from collections.abc import Sequence

from advanced_alchemy.extensions.litestar import repository, service
from advanced_alchemy.filters import OrderBy

import novamoc.db.models as m


class MaintenanceRecordTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordTypeField],
):
    class Repo(
        repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordTypeField]
    ):
        model_type = m.schema.MaintenanceRecordTypeField

    repository_type = Repo

    async def list_for_tenant(
        self, *, tenant_id: str
    ) -> Sequence[m.schema.MaintenanceRecordTypeField]:
        # ORDER BY (parent_id, id) for the GET /schema strong-ETag contract
        # (see AssetTypeFieldService).
        return await self.list(
            m.schema.MaintenanceRecordTypeField.tenant_id == tenant_id,
            OrderBy(field_name="parent_id"),
            OrderBy(field_name="id"),
        )
