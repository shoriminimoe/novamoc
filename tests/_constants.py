"""Shared constants for the test suite.

Tests use these instead of inline literals so the single source of
truth for "the canonical test tenant / user / credentials" lives in
one module. ``DEV_TENANT_ID`` is the default tenant the autouse
``tenant`` fixture in :mod:`tests.conftest` sets on the storage-layer
``current_tenant_id`` ContextVar; ``DEV_TENANT_ID_A`` /
``DEV_TENANT_ID_B`` are the two-tenant scaffolding the cross-tenant
isolation suites use.

UUID values are inlined UUIDv7 literals chosen once. Generating them
at import time (``uuid.uuid7()``) would re-randomise per process and
break the deterministic-id assertions in scenarios.

``DEV_USERNAME`` / ``DEV_PASSWORD`` are the credentials the
``dev_admin`` fixture seeds into the test app's user registry and
that the ``client`` fixture posts to ``/auth/login`` once at
construction. The password is in plain text on purpose — it never
leaves the test process.
"""

from __future__ import annotations

import uuid

DEV_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-000000000001")
DEV_TENANT_ID_A = uuid.UUID("01900000-0000-7000-8000-00000000000a")
DEV_TENANT_ID_B = uuid.UUID("01900000-0000-7000-8000-00000000000b")

DEV_USERNAME = "admin"
DEV_PASSWORD = "dev-admin-password"  # noqa: S105 — test-only credential
