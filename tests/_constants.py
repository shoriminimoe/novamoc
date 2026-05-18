"""Fixed UUIDv7 tenant identifiers for the test suite.

Tests use these constants instead of inline string literals so the
single source of truth for "the canonical test tenant" lives in one
module. ``DEV_TENANT_ID`` is the default tenant the autouse ``tenant``
fixture in :mod:`tests.conftest` sets on the storage-layer
``current_tenant_id`` ContextVar; ``DEV_TENANT_ID_A`` /
``DEV_TENANT_ID_B`` are the two-tenant scaffolding the cross-tenant
isolation suites use.

Values are inlined UUIDv7 literals chosen once. Generating them at
import time (``uuid.uuid7()``) would re-randomise per process and
break the deterministic-id assertions in scenarios.
"""

from __future__ import annotations

import uuid

DEV_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-000000000001")
DEV_TENANT_ID_A = uuid.UUID("01900000-0000-7000-8000-00000000000a")
DEV_TENANT_ID_B = uuid.UUID("01900000-0000-7000-8000-00000000000b")
