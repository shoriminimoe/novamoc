"""Authentication + tenant-context middlewares.

:class:`AuthenticationMiddleware` subclasses Litestar's
:class:`AbstractAuthenticationMiddleware` — the framework's documented
pattern for credential-resolving middleware (see
https://docs.litestar.dev/2/usage/security/abstract-authentication-middleware.html).
The base class handles path-pattern bypass (``exclude``), per-route
opt-key bypass (``exclude_from_auth``), HTTP-method exclusion (``OPTIONS``
by default), and ASGI scope filtering. Our
:meth:`AuthenticationMiddleware.authenticate_request` reads the session
payload off ``connection.session`` (populated upstream by the
SessionMiddleware mounted in :mod:`novamoc.asgi`), opens a transient
SQLAlchemy session via the registered ``SQLAlchemyPlugin``, and forwards
to :func:`resolve_principal_from_session` (M5.11, ADR-020). The
``Principal`` lands on ``scope["user"]``; the ``RequestAuth`` on
``scope["auth"]``.

:class:`TenantContextMiddleware` runs after authentication and binds
``scope["auth"].tenant_id`` to the storage-layer ``current_tenant_id``
ContextVar so the tenant-scoping listeners (``db/_listeners.py``) have
a value to read for the lifetime of the request. The contextvar is
unwound on exit including the exception path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar.middleware import ASGIMiddleware
from litestar.middleware.authentication import (
    AbstractAuthenticationMiddleware,
    AuthenticationResult,
)

from novamoc.db._tenant_context import use_tenant
from novamoc.domain.accounts._resolver import resolve_principal_from_session
from novamoc.domain.accounts._services import (
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection
    from litestar.types import ASGIApp, Receive, Scope, Send


def pick_async_alchemy_config(plugin: SQLAlchemyPlugin) -> SQLAlchemyAsyncConfig:
    """Return the single async config registered on ``plugin``.

    ``SQLAlchemyPlugin.config`` is a list (multi-binding support); we
    register exactly one async config and the isinstance check narrows
    the union for both ty and the runtime path. A second config landing
    later (read-replica, audit DB) would require disambiguating here —
    see the M5.11 spec's recorded tech debt.

    Shared with the test ``conftest`` so the production middleware and
    the ``dev_admin`` fixture both reach for the alchemy config the
    same way.

    Raises:
        RuntimeError: if no ``SQLAlchemyAsyncConfig`` is registered.
    """
    for cfg in plugin.config:
        if isinstance(cfg, SQLAlchemyAsyncConfig):
            return cfg
    msg = "No SQLAlchemyAsyncConfig registered on the SQLAlchemyPlugin"
    raise RuntimeError(msg)


class AuthenticationMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        payload = connection.session
        plugin = connection.app.plugins.get(SQLAlchemyPlugin)
        alchemy_config = pick_async_alchemy_config(plugin)
        async with alchemy_config.get_session() as db_session:
            users = UserService(session=db_session)
            memberships = UserTenantMembershipService(session=db_session)
            principal, auth = await resolve_principal_from_session(
                payload, users=users, memberships=memberships
            )
        return AuthenticationResult(user=principal, auth=auth)


class TenantContextMiddleware(ASGIMiddleware):
    """Bind the per-request RequestAuth.tenant_id to the storage-layer ContextVar.

    Stacks after AuthenticationMiddleware so scope["auth"] is already
    populated. Resets the contextvar on the way out, including
    exception paths.
    """

    async def handle(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        next_app: ASGIApp,
    ) -> None:
        auth = scope.get("auth")
        if auth is None:
            await next_app(scope, receive, send)
            return
        with use_tenant(auth.tenant_id):
            await next_app(scope, receive, send)
