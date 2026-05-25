"""HTTP controller for the ``/auth`` routes (M5.10, #91).

Thin wrapper around the module-level handler functions in
``domain.accounts._handlers``: DI resolves the services / hasher /
settings; the controller methods forward to the handlers and let the
existing ``ProblemDetailsPlugin`` render any :class:`DomainError`
(e.g. :class:`LoginFailedError`) as ``application/problem+json``.

Service DI mirrors :class:`SchemaController` — each service is wired
via ``providers.create_service_dependencies`` so the autocommit
``before_send_handler`` sees the same request-scoped session.

Two extra providers pull the ``PasswordHasher`` and :class:`AuthSettings`
off ``app.state``: M5.11 stashes the hasher and the session middleware
there at app-construction time. Keeping the resolution in DI providers
(rather than reading ``request.app.state`` inside each method) keeps the
handler signatures explicit about what they actually need.

The controller is *not* mounted by :mod:`novamoc.asgi` in this issue;
M5.11 owns the session-middleware wiring that makes ``/auth/login``
functional end-to-end, and the mount lands together with that change.
The e2e wire coverage follows in M5.12.
"""

from __future__ import annotations

from typing import Any

from advanced_alchemy.extensions.litestar import providers
from litestar import Controller, Request, get, post
from litestar.datastructures import (
    State,  # noqa: TC002  # runtime DI provider annotation
)
from litestar.di import Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.status_codes import HTTP_204_NO_CONTENT
from msgspec_ext import SecretStr

# ``PasswordHasher`` and ``AuthSettings`` are runtime DI provider
# return-type / handler-parameter annotations Litestar resolves at
# signature parse time; the imports stay at runtime.
from novamoc.api._problem_details import ProblemDetails
from novamoc.config import AuthSettings  # noqa: TC001  # runtime DI annotation
from novamoc.domain.accounts import _handlers
from novamoc.domain.accounts._password import (
    PasswordHasher,  # runtime DI annotation
)
from novamoc.domain.accounts._payloads import LoginRequest, MeResponse
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)


def _is_secret_str(typ: Any) -> bool:
    return typ is SecretStr


def _decode_secret_str(_typ: Any, obj: Any) -> SecretStr:
    """Coerce a JSON string into a :class:`SecretStr`.

    msgspec rejects ``str -> SecretStr`` without help because
    ``SecretStr`` is a subclass of ``str`` rather than ``str`` itself
    (see :func:`novamoc.domain.accounts._payloads.decode_hook` for the
    standalone dec_hook this mirrors). Litestar's ``type_decoders``
    takes ``(predicate, decoder)`` tuples; the pair is mounted on
    :class:`AuthController` so the LoginRequest body decodes cleanly.
    """
    return SecretStr(obj)


async def _provide_password_hasher(state: State) -> PasswordHasher:
    """Read the shared ``PasswordHasher`` off ``app.state``.

    M5.11 stashes the instance at app-construction time so per-request
    DI doesn't re-instantiate the wrapper. The unit tests in this issue
    set ``state.password_hasher`` directly.
    """
    return state.password_hasher


async def _provide_auth_settings(state: State) -> AuthSettings:
    """Read :class:`AuthSettings` off ``app.state.settings.auth``."""
    return state.settings.auth


class AuthController(Controller):
    path = "/auth"
    tags = ("auth",)

    type_decoders = ((_is_secret_str, _decode_secret_str),)

    dependencies = (
        {
            "password_hasher": Provide(_provide_password_hasher),
            "auth_settings": Provide(_provide_auth_settings),
        }
        | providers.create_service_dependencies(UserService, "users")
        | providers.create_service_dependencies(
            UserTenantMembershipService, "memberships"
        )
        | providers.create_service_dependencies(TenantService, "tenants")
    )

    @post(
        "/login",
        status_code=HTTP_204_NO_CONTENT,
        responses={
            401: ResponseSpec(
                ProblemDetails,
                description="Credentials were not accepted",
                media_type="application/problem+json",
            ),
        },
        exclude_from_auth=True,
    )
    async def login(
        self,
        request: Request,
        data: LoginRequest,
        users: UserService,
        memberships: UserTenantMembershipService,
        password_hasher: PasswordHasher,
    ) -> None:
        await _handlers.login(
            request=request,
            data=data,
            users=users,
            memberships=memberships,
            password_hasher=password_hasher,
        )

    @post("/logout", status_code=HTTP_204_NO_CONTENT)
    async def logout(self, request: Request) -> None:
        await _handlers.logout(request=request)

    @get("/me")
    async def me(self, request: Request, tenants: TenantService) -> MeResponse:
        return await _handlers.me(request=request, tenants=tenants)
