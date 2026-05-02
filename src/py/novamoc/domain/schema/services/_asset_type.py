import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetType]):
        model_type = m.schema.AssetType

    repository_type = Repo
