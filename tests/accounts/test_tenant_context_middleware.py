"""TenantContextMiddleware sets the storage-layer tenant ContextVar."""

from __future__ import annotations

import pytest
from litestar import Litestar, get
from litestar.middleware.base import DefineMiddleware
from litestar.testing import AsyncTestClient

from novamoc.db._tenant_context import current_tenant_id
from novamoc.domain.accounts import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
)
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN


async def test_middleware_sets_contextvar_during_request() -> None:
    seen: list[str | None] = []

    @get("/__probe")
    async def probe() -> dict[str, str | None]:
        seen.append(current_tenant_id.get())
        return {"ok": "yes"}

    app = Litestar(
        route_handlers=[probe],
        middleware=[
            DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
            TenantContextMiddleware(),
        ],
    )
    async with AsyncTestClient(app) as client:
        response = await client.get(
            "/__probe", headers={"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}
        )
        assert response.status_code == 200
        assert seen == ["t1"]


@pytest.mark.no_tenant
async def test_middleware_resets_contextvar_after_request() -> None:
    """After a request returns, the calling code's contextvar is unchanged."""

    @get("/__probe")
    async def probe() -> dict[str, str]:
        return {"ok": "yes"}

    app = Litestar(
        route_handlers=[probe],
        middleware=[
            DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi"),
            TenantContextMiddleware(),
        ],
    )
    async with AsyncTestClient(app) as client:
        await client.get(
            "/__probe", headers={"Authorization": f"Bearer {_TENANT_T1_DEV_TOKEN}"}
        )
    # Contextvar in the test process is unchanged after the request.
    assert current_tenant_id.get() is None
