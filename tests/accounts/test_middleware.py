from __future__ import annotations

from litestar import Litestar, Request, get
from litestar.middleware.base import DefineMiddleware
from litestar.testing import AsyncTestClient

from novamoc.domain.accounts import (
    AuthenticationMiddleware,
    RequestAuth,
)
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN
from tests._constants import DEV_TENANT_ID

_VALID_AUTH = {"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}


@get("/probe")
async def _probe(request: Request) -> dict:
    return {"tenant_id": request.auth.tenant_id}


@get("/openapi/probe-bypass")
async def _bypass_probe(request: Request) -> dict:
    # The middleware excludes ^/openapi, so request.auth is unset on this path.
    return {"has_auth": "auth" in request.scope}


@get("/explicit-public", opt={"exclude_from_auth": True})
async def _explicit_public(request: Request) -> dict:
    # Per-route opt-out via the documented opt key.
    return {"has_auth": "auth" in request.scope}


def _app() -> Litestar:
    return Litestar(
        route_handlers=[_probe, _bypass_probe, _explicit_public],
        middleware=[
            DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
        ],
    )


async def test_valid_bearer_populates_request_auth() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/probe", headers=_VALID_AUTH)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"tenant_id": str(DEV_TENANT_ID)}


async def test_missing_bearer_renders_401() -> None:
    """``AbstractAuthenticationMiddleware`` raises ``NotAuthorizedException``
    (our :class:`TenantResolutionError`); the framework's HTTPException
    handler renders it as a 401 even without a custom problem-details
    mapper. (The real app *does* register the mapper to control the
    type-URI leaf; this test just pins the base contract.)"""
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/probe")
        assert resp.status_code == 401, resp.text


async def test_excluded_path_pattern_bypasses_authentication() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/openapi/probe-bypass")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"has_auth": False}


async def test_exclude_from_auth_opt_key_bypasses_authentication() -> None:
    """Per-route opt-out lives on the handler decorator; co-located with the
    route, no path-pattern drift."""
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/explicit-public")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"has_auth": False}


async def test_authenticated_request_has_typed_request_auth_on_scope() -> None:
    async with AsyncTestClient(_app()) as client:
        resp = await client.get("/probe", headers=_VALID_AUTH)
        expected = str(RequestAuth(tenant_id=DEV_TENANT_ID).tenant_id)
        assert resp.json() == {"tenant_id": expected}
