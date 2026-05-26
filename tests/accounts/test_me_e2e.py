"""Wire-level e2e tests for ``GET /auth/me`` (M5.12, issue #93).

Returns the resolved principal and active tenant for the request's
session. Unauthenticated requests render the standard
``tenant_not_resolved`` 401 — the same problem-details body every
other authed endpoint emits on missing/invalid credentials.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from tests._constants import DEV_TENANT_ID, DEV_USERNAME

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


pytestmark = pytest.mark.no_tenant


async def test_authenticated_me_returns_user_and_tenant(
    client: AsyncTestClient,
) -> None:
    resp = await client.get("/auth/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["username"] == DEV_USERNAME
    # The user UUID is server-assigned at seed time; assert only that
    # it parses cleanly.
    assert uuid.UUID(body["user"]["id"])

    assert body["tenant"]["id"] == str(DEV_TENANT_ID)
    # ``seed_dev_admin`` pins the tenant display name; assert against
    # the same literal so a fixture rename surfaces here.
    assert body["tenant"]["display_name"] == "Acme"


async def test_unauthenticated_me_returns_401_tenant_not_resolved(
    unauth_client: AsyncTestClient,
) -> None:
    resp = await unauth_client.get("/auth/me")

    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"
