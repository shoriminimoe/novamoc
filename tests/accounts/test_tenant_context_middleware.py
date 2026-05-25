"""``TenantContextMiddleware`` binds ``request.auth.tenant_id`` to the ContextVar.

The middleware reads ``scope["auth"]`` (populated by
``AuthenticationMiddleware``) and calls
:func:`novamoc.db._tenant_context.use_tenant` for the lifetime of the
request, so the tenant-scoping listeners have a value to read. These
tests pin the in-request behaviour and the post-request reset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from litestar import get
from litestar.testing import AsyncTestClient

from novamoc.db._tenant_context import current_tenant_id
from tests._constants import DEV_TENANT_ID

if TYPE_CHECKING:
    from uuid import UUID

    from litestar import Litestar

    from tests.conftest import DevAdmin


_seen: list[UUID | None] = []


@get("/__probe_tenant")
async def _probe() -> dict[str, str]:
    _seen.append(current_tenant_id.get())
    return {"ok": "yes"}


async def test_middleware_sets_contextvar_during_request(
    app: Litestar, dev_admin: DevAdmin
) -> None:
    _seen.clear()
    app.register(_probe)
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login",
            json={"username": dev_admin.username, "password": dev_admin.password},
        )
        assert resp.status_code == 204, resp.text

        response = await c.get("/__probe_tenant")
        assert response.status_code == 200
        assert _seen == [DEV_TENANT_ID]


@pytest.mark.no_tenant
async def test_middleware_resets_contextvar_after_request(
    app: Litestar, dev_admin: DevAdmin
) -> None:
    """After a request returns, the calling code's contextvar is unchanged.

    Opts out of the autouse ``tenant`` fixture so the test process
    enters the request with ``current_tenant_id == None`` and we can
    assert the middleware did not leak its bound value.
    """
    _seen.clear()
    app.register(_probe)
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login",
            json={"username": dev_admin.username, "password": dev_admin.password},
        )
        assert resp.status_code == 204, resp.text
        await c.get("/__probe_tenant")
    # Contextvar in the test process is unchanged after the request.
    assert current_tenant_id.get() is None
