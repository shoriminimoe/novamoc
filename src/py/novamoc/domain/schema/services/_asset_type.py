import novamoc.db.models as m
from advanced_alchemy.extensions.litestar import repository, service


class AssetTypeService(service.SQLAlchemyAsyncRepositoryService[m.schema.AssetType]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.AssetType]):
        model_type = m.schema.AssetType

    repository_type = Repo

    # TODO: implement the activate_asset_type command per ADR-008. Server
    # infers the operation from projection state — the client never declares
    # a mode. Branches:
    #   - Missing      + empty payload      -> reject ("definition required to create")
    #   - Missing      + non-empty payload  -> create from payload (active = true)
    #   - Tombstoned   + empty payload      -> resurrect (flip active = true, inherit existing definition)
    #   - Tombstoned   + non-empty payload  -> reject (resurrect + follow-up update_*)
    #   - Active       + empty payload      -> no-op (idempotent ack)
    #   - Active       + non-empty payload  -> reject ("use update_*")
    # Same matrix applies to every other activate_* command.
