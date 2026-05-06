"""Programming-error exceptions raised by the tenant-scoping listeners.

These are not user-facing failures and do not get problem-details
renderers — the storage layer raises them when a tenant-scoped table
is touched without a tenant scope or when a write disagrees with the
current tenant context. Handlers must not catch them; they propagate
to a 500 from the framework so the bug is visible in CI/dev.
"""

from __future__ import annotations


class UnscopedQueryError(RuntimeError):
    """A statement against a tenant-scoped table executed without a tenant scope."""


class CrossTenantWriteError(RuntimeError):
    """An ORM instance was flushed with a tenant_id different from the contextvar."""
