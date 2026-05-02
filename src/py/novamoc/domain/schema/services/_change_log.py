from __future__ import annotations

from typing import Any
from uuid import UUID

from advanced_alchemy.extensions.litestar import repository, service

import novamoc.db.models as m
from novamoc.domain.schema._commands import SchemaCommand


class SchemaChangeLogService(
    service.SQLAlchemyAsyncRepositoryService[m.schema.SchemaChangeLog]
):
    """Append-only log of accepted schema commands.

    The repository pattern fits poorly here — the table is write-only from
    the endpoint's perspective and each row is one user action — but using
    advanced-alchemy's service keeps Litestar DI uniform across services.
    """

    class Repo(repository.SQLAlchemyAsyncRepository[m.schema.SchemaChangeLog]):
        model_type = m.schema.SchemaChangeLog

    repository_type = Repo

    async def append(
        self,
        *,
        tenant_id: str,
        command: SchemaCommand,
        entity_id: UUID,
        payload: dict[str, Any],
    ) -> m.schema.SchemaChangeLog:
        return await self.create(
            data={
                "tenant_id": tenant_id,
                "command": str(command.value),
                "entity_id": entity_id,
                "payload": payload,
            },
            auto_commit=False,
        )
