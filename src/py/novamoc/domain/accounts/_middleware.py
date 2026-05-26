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
SessionMiddleware mounted in :mod:`novamoc.asgi`), acquires a SQLAlchemy
session via
``alchemy_config.provide_session(connection.app.state, connection.scope)``
— the pattern advanced-alchemy documents for guards/middleware (see
https://advanced-alchemy.litestar.dev/latest/usage/frameworks/litestar.html#sessions-in-application).
``provide_session`` is idempotent per scope: any handler that later
binds ``db_session: AsyncSession`` via DI receives the same session,
and the plugin's ``before_send_handler="autocommit"`` hook handles
commit/rollback at response time. The middleware does not own the
session lifecycle. ``Principal`` lands on ``scope["user"]``;
``RequestAuth`` on ``scope["auth"]``.

The ``alchemy_config`` reference is injected at app-construction time
via ``DefineMiddleware(AuthenticationMiddleware, alchemy_config=...)``
— DI providers are not reachable from middleware (they resolve at
route-handler invocation time), and a constructor-time inject is the
documented Litestar idiom for "middleware needs a singleton."

:class:`TenantContextMiddleware` runs after authentication and binds
``scope["auth"].tenant_id`` to the storage-layer ``current_tenant_id``
ContextVar so the tenant-scoping listeners (``db/_listeners.py``) have
a value to read for the lifetime of the request. The contextvar is
unwound on exit including the exception path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
    from litestar.connection import ASGIConnection
    from litestar.types import ASGIApp, Receive, Scope, Send


class AuthenticationMiddleware(AbstractAuthenticationMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        alchemy_config: SQLAlchemyAsyncConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(app=app, **kwargs)
        self._alchemy_config = alchemy_config

    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        db_session = self._alchemy_config.provide_session(
            connection.app.state, connection.scope
        )
        users = UserService(session=db_session)
        memberships = UserTenantMembershipService(session=db_session)
        principal, auth = await resolve_principal_from_session(
            connection.session, users=users, memberships=memberships
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
