import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class MaintenanceRecordTypeService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.MaintenanceRecordType],
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.MaintenanceRecordType]):
        model_type = m.schema.MaintenanceRecordType

    repository_type = Repo
