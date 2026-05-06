"""Per-request aggregator of the services every command handler uses.

Lives here rather than in ``_dispatch`` or ``_handlers/__init__`` so
both can import it without setting up a circular dependency. Tests and
the controller import :class:`ServiceBundle` directly from this module
(no re-exports).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from novamoc.domain.accounts import RequestAuth
    from novamoc.domain.schema._outcomes import SchemaCommitOutcome
    from novamoc.domain.schema.services import (
        AssetTypeFieldService,
        AssetTypeService,
        MaintenanceRecordTypeFieldService,
        MaintenanceRecordTypeService,
        SchemaChangeLogService,
    )


@dataclass(frozen=True, slots=True)
class ServiceBundle:
    asset_type: AssetTypeService
    asset_type_field: AssetTypeFieldService
    maintenance_record_type: MaintenanceRecordTypeService
    maintenance_record_type_field: MaintenanceRecordTypeFieldService
    change_log: SchemaChangeLogService


# PEP 695 `type` statement: the right-hand side is lazily evaluated, so the
# names used here can stay under `if TYPE_CHECKING:`.
type Handler = Callable[
    [ServiceBundle, RequestAuth, Any], Awaitable[SchemaCommitOutcome]
]


__all__ = ("Handler", "ServiceBundle")
