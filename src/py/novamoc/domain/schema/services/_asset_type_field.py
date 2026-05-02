import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeFieldService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.AssetTypeField]
):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetTypeField]):
        model_type = m.schema.AssetTypeField

    repository_type = Repo
