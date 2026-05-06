"""Reusable declarative mixins for db models.

This module is intentionally not scoped to tenancy in its name —
future mixins (timestamping flavours, soft-delete, etc.) belong here
alongside ``TenantScopedMixin``.
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column


@declarative_mixin
class TenantScopedMixin:
    """Mark a mapped class as tenant-scoped.

    Adds ``tenant_id`` as a primary-key column with ``sort_order=-200``,
    so when composed with a UUID/BigInt PK base the composite PK leads
    with ``tenant_id`` (ADR-014). Targeted by the three enforcement
    listeners in ``db/_listeners.py``, which identify "tenant-scoped
    table" by column presence rather than this class.
    """

    tenant_id: Mapped[str] = mapped_column(primary_key=True, sort_order=-200)
