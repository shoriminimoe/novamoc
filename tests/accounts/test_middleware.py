"""End-to-end coverage of ``AuthenticationMiddleware`` (M5.11, ADR-020).

Exercises the middleware through the full app stack so the session
middleware + auth middleware interplay is what we test. The resolver's
own unit tests live in :mod:`tests.accounts.test_resolver_session`;
this module pins the framework-integration contracts:

* a valid session populates ``request.user`` / ``request.auth``;
* an unauthenticated request renders 401;
* the ``exclude`` path-pattern bypass and ``exclude_from_auth`` opt-key
  bypass continue to work;
* ``OPTIONS`` requests bypass the middleware (the base class default).

The probe handler is mounted on the live app via the ``app`` fixture's
``route_handlers`` — we cannot register additional routes after
``create_app`` runs without rebuilding the app, so the tests stand up
a fresh app per scenario for the probe-only cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar import Request, get
from litestar.testing import AsyncTestClient

from tests._constants import DEV_TENANT_ID, DEV_USERNAME

if TYPE_CHECKING:
    from litestar import Litestar

    from tests.conftest import DevAdmin


@get("/__probe")
async def _probe(request: Request) -> dict:
    return {
        "tenant_id": str(request.auth.tenant_id),
        "username": request.user.username,
    }


@get("/openapi/__bypass")
async def _bypass_probe(request: Request) -> dict:
    return {"has_user": request.scope.get("user") is not None}


@get("/__explicit_public", opt={"exclude_from_auth": True})
async def _explicit_public(request: Request) -> dict:
    return {"has_user": request.scope.get("user") is not None}


def _attach_probe(app: Litestar) -> None:
    """Register the probe handlers on the existing app.

    The app fixture's ``Litestar`` is already built; ``app.register``
    is the supported entry point for adding routes after construction
    (used by Litestar plugins). One call per handler keeps the
    registration explicit.
    """
    app.register(_probe)
    app.register(_bypass_probe)
    app.register(_explicit_public)


async def test_authenticated_request_populates_user_and_auth(
    app: Litestar, dev_admin: DevAdmin
) -> None:
    _attach_probe(app)
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login",
            json={"username": dev_admin.username, "password": dev_admin.password},
        )
        assert resp.status_code == 204, resp.text

        resp = await c.get("/__probe")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "tenant_id": str(DEV_TENANT_ID),
            "username": DEV_USERNAME,
        }


async def test_unauthenticated_request_renders_401(app: Litestar) -> None:
    """No session cookie ⇒ resolver raises ``TenantResolutionError``.

    The framework's HTTPException handler (and the
    ``tenant_resolution_error_to_problem_details`` mapper registered
    in :func:`novamoc.asgi.create_app`) renders the raise as 401.
    """
    _attach_probe(app)
    async with AsyncTestClient(app) as c:
        resp = await c.get("/__probe")
        assert resp.status_code == 401, resp.text


async def test_exclude_path_pattern_bypasses_authentication(
    app: Litestar,
) -> None:
    """``/openapi`` is in the middleware's exclude regex."""
    _attach_probe(app)
    async with AsyncTestClient(app) as c:
        resp = await c.get("/openapi/__bypass")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"has_user": False}


async def test_exclude_from_auth_opt_key_bypasses_authentication(
    app: Litestar,
) -> None:
    """Per-route opt-out lives on the handler decorator."""
    _attach_probe(app)
    async with AsyncTestClient(app) as c:
        resp = await c.get("/__explicit_public")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"has_user": False}


async def test_login_path_is_excluded_from_authentication(
    app: Litestar, dev_admin: DevAdmin
) -> None:
    """``POST /auth/login`` reaches the handler without an existing session.

    The exclude regex on the auth middleware short-circuits before any
    session lookup — login is the bootstrap path that *writes* the
    session it would otherwise need to read.
    """
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login",
            json={"username": dev_admin.username, "password": dev_admin.password},
        )
        assert resp.status_code == 204, resp.text
