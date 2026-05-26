"""Wire-level e2e tests for ``POST /auth/login`` (M5.12, issue #93).

Drives the live app through ``unauth_client``: the test seeds the
canonical admin (via :func:`seed_dev_admin`) and then exercises the
login endpoint directly. The :func:`tests.conftest.client` fixture
uses the same handshake, but discards the response — these tests
own the assertions on status code, ``Set-Cookie``, and the
problem-details body.

The anti-enumeration assertion
(:func:`test_wrong_password_and_unknown_user_indistinguishable`) is
the load-bearing one in this module: a regression there is a
credential leak, not a styling issue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)

from novamoc.domain.accounts._services import (
    UserService,
    UserTenantMembershipService,
)
from tests._constants import DEV_PASSWORD, DEV_USERNAME
from tests.conftest import seed_dev_admin

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


# The auth registry tables (``users``, ``tenants``, ``user_tenant_memberships``)
# are not tenant-scoped, so the e2e flow does not need the autouse
# ``tenant`` contextvar. The middleware sets it on the request path
# when the cookie resolves; the login path itself bypasses auth.
pytestmark = pytest.mark.no_tenant


async def _session_factory(app: Litestar):
    """Return an ``AsyncSession`` bound to the live app's plugin config.

    Mirrors the pattern :func:`seed_dev_admin` uses — code outside the
    request lifecycle reaches the plugin's config via ``app.plugins``,
    then opens a session with ``alchemy_config.get_session()``.
    """
    plugin = app.plugins.get(SQLAlchemyPlugin)
    alchemy_config = next(
        c for c in plugin.config if isinstance(c, SQLAlchemyAsyncConfig)
    )
    return alchemy_config.get_session()


async def _disable_admin(app: Litestar) -> None:
    """Stamp ``disabled_at`` on the seeded admin user."""
    async with await _session_factory(app) as db_session:
        users = UserService(session=db_session)
        user = await users.get_by_username(DEV_USERNAME)
        assert user is not None
        await users.update(
            data={"disabled_at": datetime.now(tz=UTC)},
            item_id=user.id,
            auto_commit=False,
        )
        await db_session.commit()


async def _delete_admin_membership(app: Litestar) -> None:
    """Delete the seeded admin's membership row.

    Reproduces the transient zero-membership state ADR-020 folds into
    the anti-enumeration response.
    """
    async with await _session_factory(app) as db_session:
        users = UserService(session=db_session)
        memberships = UserTenantMembershipService(session=db_session)
        user = await users.get_by_username(DEV_USERNAME)
        assert user is not None
        membership = await memberships.get_for_user(user.id)
        assert membership is not None
        # ``UserTenantMembership`` has composite PK ``(user_id, tenant_id)``;
        # ``delete`` accepts that tuple in declaration order.
        await memberships.delete(
            item_id=(membership.user_id, membership.tenant_id),
            auto_commit=False,
        )
        await db_session.commit()


async def test_valid_credentials_returns_204_with_session_cookie(
    app: Litestar, unauth_client: AsyncTestClient
) -> None:
    await seed_dev_admin(app)

    resp = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
    )

    assert resp.status_code == 204, resp.text
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith("novamoc_session=")
    # The session id between the ``=`` and the first ``;`` is non-empty.
    session_value = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert session_value
    # Flags are case-insensitive per RFC 6265; httpx preserves the
    # casing Litestar emits.
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered


async def test_wrong_password_returns_401_login_failed(
    app: Litestar, unauth_client: AsyncTestClient
) -> None:
    await seed_dev_admin(app)

    resp = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME, "password": "not-the-password"},
    )

    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/login_failed.html"


async def test_unknown_username_returns_401_login_failed(
    unauth_client: AsyncTestClient,
) -> None:
    # No seed — the user table is empty, so any username is "unknown".
    resp = await unauth_client.post(
        "/auth/login",
        json={"username": "ghost", "password": DEV_PASSWORD},
    )

    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/login_failed.html"


async def test_wrong_password_and_unknown_user_indistinguishable(
    app: Litestar, unauth_client: AsyncTestClient
) -> None:
    """Anti-enumeration: byte-equal bodies modulo the ``instance`` UUID.

    A regression here is a credential leak — the test name is
    deliberately verbose so a grep across the suite surfaces it.
    """
    await seed_dev_admin(app)

    wrong_pw = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME, "password": "not-the-password"},
    )
    unknown = await unauth_client.post(
        "/auth/login",
        json={"username": "ghost", "password": DEV_PASSWORD},
    )

    assert wrong_pw.status_code == 401, wrong_pw.text
    assert unknown.status_code == 401, unknown.text
    assert {k: v for k, v in wrong_pw.json().items() if k != "instance"} == {
        k: v for k, v in unknown.json().items() if k != "instance"
    }


async def test_disabled_user_returns_401_login_failed(
    app: Litestar, unauth_client: AsyncTestClient
) -> None:
    await seed_dev_admin(app)
    await _disable_admin(app)

    resp = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
    )

    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/login_failed.html"


async def test_zero_membership_returns_401_login_failed(
    app: Litestar, unauth_client: AsyncTestClient
) -> None:
    """User exists, password correct, no membership row.

    Pins that the login handler folds the transient invariant
    violation into the anti-enumeration body rather than branching on
    it. The M5.4 N:1 write-time invariant means a steady-state
    multi-membership condition cannot reach this path.
    """
    await seed_dev_admin(app)
    await _delete_admin_membership(app)

    resp = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
    )

    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "http://test/problems/login_failed.html"


async def test_missing_field_returns_400_invalid_payload_shape(
    unauth_client: AsyncTestClient,
) -> None:
    resp = await unauth_client.post(
        "/auth/login",
        json={"username": DEV_USERNAME},
    )

    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"


async def test_extra_field_returns_400_invalid_payload_shape(
    unauth_client: AsyncTestClient,
) -> None:
    """``LoginRequest`` is ``forbid_unknown_fields=True`` (M5.8)."""
    resp = await unauth_client.post(
        "/auth/login",
        json={
            "username": DEV_USERNAME,
            "password": DEV_PASSWORD,
            "extra": True,
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "http://test/problems/invalid_payload_shape.html"
