"""Application-level configuration constants.

Today this module is empty. Pre-auth dev configuration that previously
lived here (the ``KNOWN_TENANT_IDS`` stub) was retired by ADR-017 — the
tenant identity now comes from the request envelope (Bearer token →
``RequestAuth``) resolved by ``AuthenticationMiddleware``.
"""

from __future__ import annotations
