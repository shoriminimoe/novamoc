"""Authentication / tenant-registry tables (ADR-020).

These rows describe *who* the tenants and users are; they are not
themselves tenant-scoped. The storage-layer listeners in
``db/_listeners.py`` short-circuit naturally because the tables have no
``tenant_id`` column.
"""

from ._session import Session
from ._tenant import Tenant

__all__ = ("Session", "Tenant")
