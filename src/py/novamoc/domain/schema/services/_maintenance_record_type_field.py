from collections.abc import Sequence

import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


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
        return await self.list(
            m.schema.MaintenanceRecordTypeField.tenant_id == tenant_id
        )
