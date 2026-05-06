from advanced_alchemy.extensions.litestar import repository, service

import novamoc.db.models as m


class MaintenanceRecordTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordTypeField],
):
    class Repo(
        repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordTypeField]
    ):
        model_type = m.schema.MaintenanceRecordTypeField

    repository_type = Repo
