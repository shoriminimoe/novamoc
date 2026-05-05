"""Authentication middleware that resolves the per-request ``RequestAuth``.

Subclasses :class:`litestar.middleware.authentication.AbstractAuthenticationMiddleware`
— the framework's documented pattern for credential-resolving middleware
(see https://docs.litestar.dev/2/usage/security/abstract-authentication-middleware.html).

The base class handles path-pattern bypass (``exclude``), opt-key bypass
(``exclude_from_auth``), HTTP-method exclusion (``OPTIONS`` by default),
and ASGI scope filtering. Our :meth:`authenticate_request` only has to
parse the credential and produce an :class:`AuthenticationResult` —
``user`` stays ``None`` until the user model lands; ``auth`` carries the
resolved :class:`RequestAuth` and is read by handlers as
``request.auth`` (or via the :func:`provide_auth` DI provider).

Configured at app construction with the OpenAPI doc bypass:

    DefineMiddleware(AuthenticationMiddleware, exclude=r"^/openapi")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.middleware.authentication import (
    AbstractAuthenticationMiddleware,
    AuthenticationResult,
)

from novamoc.domain.accounts import RequestAuth
from novamoc.domain.accounts._resolver import resolve_tenant

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection


class AuthenticationMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        tenant_id = resolve_tenant(connection.headers)
        return AuthenticationResult(user=None, auth=RequestAuth(tenant_id=tenant_id))
