"""Account-domain services (ADR-020).

Thin advanced-alchemy wrappers; the registry tables are not
tenant-scoped, so callers do not pass a ``tenant_id`` and the storage
listeners short-circuit on column absence.
"""

from advanced_alchemy.extensions.litestar import repository, service

from novamoc.db.models._auth import Tenant


class TenantService(service.SQLAlchemyAsyncRepositoryService[Tenant]):
    class Repo(repository.SQLAlchemyAsyncRepository[Tenant]):
        model_type = Tenant

    repository_type = Repo
