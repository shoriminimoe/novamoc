import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.AssetType]):
        model_type = m.AssetType

    repository_type = Repo
