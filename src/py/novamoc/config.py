"""Application-level configuration constants.

Today this is a thin module — most config is wired in :mod:`novamoc.asgi`
via the SQLAlchemy plugin. Constants here are values that need to be
referenced from multiple places and would otherwise live as string
literals scattered across the code.
"""

from __future__ import annotations

# Single hardcoded tenant for the pre-auth dev environment. Aligned with
# the existing test fixtures under ``tests/data/fixtures/`` which seed
# ``tenant_id: "t1"``. Replaced by a real tenant registry once auth and
# tenant management land — see issue #19.
KNOWN_TENANT_IDS: frozenset[str] = frozenset({"t1"})
