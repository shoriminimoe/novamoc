"""Wire-level e2e tests for ``POST /auth/logout`` (M5.12, issue #93).

Logout is not fire-and-forget: the route requires a resolved session
to reach the handler, so an unauthenticated request renders 401
``tenant_not_resolved`` the same as any other authed endpoint. Once
the handler runs, the session row is deleted server-side and the
cookie is invalidated wire-side via a ``Max-Age=0`` ``Set-Cookie``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


pytestmark = pytest.mark.no_tenant


async def test_authenticated_logout_returns_204_and_clears_cookie(
    client: AsyncTestClient,
) -> None:
    pre_logout = client.cookies["novamoc_session"]

    resp = await client.post("/auth/logout")

    assert resp.status_code == 204, resp.text
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith("novamoc_session=")
    # The session middleware invalidates wire-side by replacing the
    # cookie value with the cleared marker — the new value must not
    # equal the pre-logout session id, and the resolver rejects the
    # marker server-side (asserted in the subsequent-request test).
    new_value = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert new_value != pre_logout


async def test_subsequent_request_on_cleared_cookie_returns_401(
    client: AsyncTestClient,
) -> None:
    """After logout the server-side session row is gone, so the cookie
    that httpx still carries no longer resolves.

    The resolver folds "session payload missing" / "session id unknown
    to the backend" into the same :class:`TenantResolutionError`.
    """
    logout = await client.post("/auth/logout")
    assert logout.status_code == 204, logout.text

    resp = await client.get("/auth/me")

    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"


async def test_unauthenticated_logout_returns_401_tenant_not_resolved(
    unauth_client: AsyncTestClient,
) -> None:
    """``/auth/logout`` is not in the auth-middleware ``exclude`` regex.

    Without a session there is nothing to log out from — the middleware
    rejects the request before the handler runs.
    """
    resp = await unauth_client.post("/auth/logout")

    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/tenant_not_resolved.html"
