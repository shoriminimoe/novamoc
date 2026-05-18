"""Per-request tenant context.

The ContextVar is set by `TenantContextMiddleware` for every HTTP
request after credential resolution. Tests and scripts that need to
exercise the storage layer outside the HTTP lifecycle use the
`use_tenant` context manager.

`SKIP_TENANT_FILTER` is the execution-option key that suppresses
Layer 1's loader-criteria injection and Layer 3's WHERE/VALUES
backstop. Layer 2's auto-stamp behaviour is unaffected by it. Used
only by deliberate cross-tenant administrative operations; v1 has no
production callers.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

current_tenant_id: ContextVar[UUID | None] = ContextVar(
    "novamoc_current_tenant_id", default=None
)

SKIP_TENANT_FILTER = "novamoc_skip_tenant_filter"


@contextmanager
def use_tenant(tenant_id: UUID) -> Iterator[None]:
    """Set the tenant context for the duration of the with-block.

    Resets to the prior value (including None) on exit, even if the
    block raises.
    """
    token = current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)
