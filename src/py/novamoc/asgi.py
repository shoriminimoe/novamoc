# Imports inside ``create_app`` are deliberately deferred to keep CLI /
# import-time work cheap; ``create_app`` is only called when actually serving.
# ruff: noqa: PLC0415
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
    from litestar import Litestar

    from novamoc.config import Settings


def create_app(
    settings: Settings | None = None,
    *,
    alchemy_config: SQLAlchemyAsyncConfig | None = None,
) -> Litestar:
    """Create the ASGI app.

    Args:
        settings: App-wide settings; ``Settings()`` is read from env vars
            if omitted.
        alchemy_config: Optional pre-built SQLAlchemy config — production
            leaves this ``None`` and lets ``build_alchemy_config(settings)``
            run; tests pass a config bound to an engine they've already
            populated (see ``tests/conftest.py``'s ``app`` fixture).
    """

    import msgspec
    from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
    from advanced_alchemy.extensions.litestar.session import (
        SQLAlchemyAsyncSessionBackend,
    )
    from litestar import Litestar
    from litestar.datastructures import State
    from litestar.exceptions import ValidationException
    from litestar.middleware.base import DefineMiddleware
    from litestar.middleware.session import SessionMiddleware
    from litestar.middleware.session.server_side import ServerSideSessionConfig
    from litestar.openapi.config import OpenAPIConfig
    from litestar.plugins.problem_details import (
        ProblemDetailsConfig,
        ProblemDetailsPlugin,
    )
    from litestar.static_files import create_static_files_router
    from litestar_granian import GranianPlugin

    # Register tenant-scoping event handlers on SQLAlchemy.
    import novamoc.db._listeners  # noqa: F401
    from novamoc.api._problem_details import (
        make_domain_error_converter,
        make_litestar_validation_error_converter,
        make_msgspec_validation_error_converter,
        make_tenant_resolution_error_converter,
    )
    from novamoc.config import Settings, problem_html_dir
    from novamoc.db.config import build_alchemy_config
    from novamoc.db.models._auth import Session as SessionModel
    from novamoc.domain._errors import DomainError
    from novamoc.domain.accounts import (
        AuthController,
        AuthenticationMiddleware,
        PasswordHasher,
        TenantContextMiddleware,
        TenantResolutionError,
    )
    from novamoc.domain.events.controllers import EventsController
    from novamoc.domain.schema.controllers import SchemaController
    from novamoc.domain.snapshot.controllers import SnapshotController

    s = settings if settings is not None else Settings()

    cfg = alchemy_config if alchemy_config is not None else build_alchemy_config(s)

    base_url = s.app.docs_base_url
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            DomainError: make_domain_error_converter(base_url),
            TenantResolutionError: make_tenant_resolution_error_converter(base_url),
            msgspec.ValidationError: make_msgspec_validation_error_converter(base_url),
            ValidationException: make_litestar_validation_error_converter(base_url),
        },
    )

    problem_docs_router = create_static_files_router(
        path="/problems",
        directories=[str(problem_html_dir())],
        name="problems",
    )

    plugins = [
        *([GranianPlugin()] if s.server.granian else []),
        SQLAlchemyPlugin(config=cfg),
        ProblemDetailsPlugin(config=problem_details_config),
    ]

    # ``SQLAlchemyAsyncSessionBackend`` is constructed directly (rather
    # than via ``ServerSideSessionConfig.middleware``) because the
    # config's ``.middleware`` property instantiates the backend with
    # ``config`` only, whereas this backend requires ``config +
    # alchemy_config + model``. Mount via
    # ``DefineMiddleware(SessionMiddleware, backend=...)``.
    session_config = ServerSideSessionConfig(
        key=s.auth.session_cookie_name,
        max_age=s.auth.session_ttl_seconds,
        secure=s.auth.session_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    session_backend = SQLAlchemyAsyncSessionBackend(
        config=session_config,
        alchemy_config=cfg,
        model=SessionModel,
    )

    password_hasher = PasswordHasher(
        time_cost=s.auth.argon2_time_cost,
        memory_cost_kib=s.auth.argon2_memory_cost_kib,
        parallelism=s.auth.argon2_parallelism,
    )

    return Litestar(
        route_handlers=[
            AuthController,
            SchemaController,
            EventsController,
            SnapshotController,
            problem_docs_router,
        ],
        middleware=[
            # 1. read/write the session cookie ↔ ``scope["session"]``.
            DefineMiddleware(SessionMiddleware, backend=session_backend),
            # 2. read ``scope["session"]`` → ``scope["user"]`` /
            # ``scope["auth"]``. ``alchemy_config`` is injected here so
            # the middleware can call ``provide_session(state, scope)``
            # — the advanced-alchemy-documented pattern for guards /
            # middleware. ``/auth/login`` is excluded because login
            # is the bootstrap path that *writes* the session;
            # ``/openapi`` and ``/problems`` stay public. The trailing
            # ``(/|$)`` anchors each entry so a future
            # ``/auth/login/oauth`` (or similar) doesn't silently
            # inherit the bypass.
            DefineMiddleware(
                AuthenticationMiddleware,
                alchemy_config=cfg,
                exclude=r"^/(openapi|problems|auth/login)(/|$)",
            ),
            # 3. read ``scope["auth"].tenant_id`` → ContextVar so the
            # storage-layer listeners have a value for the request.
            TenantContextMiddleware(),
        ],
        plugins=plugins,
        # ``state.settings`` is read by per-controller DI providers
        # (see ``EventsController.dependencies``) so handlers receive
        # only the narrow slice they need rather than the whole tree.
        # ``state.password_hasher`` is the hot-path login dependency
        # M5.10's ``AuthController`` pulls via DI.
        state=State({"settings": s, "password_hasher": password_hasher}),
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
