# Imports inside ``create_app`` are deliberately deferred to keep CLI /
# import-time work cheap; ``create_app`` is only called when actually serving.
# ruff: noqa: PLC0415
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar

    from novamoc.config import Settings


def create_app(settings: Settings | None = None) -> Litestar:
    """Create the ASGI app."""

    import msgspec
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        EngineConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.exceptions import ValidationException
    from litestar.middleware.base import DefineMiddleware
    from litestar.openapi.config import OpenAPIConfig
    from litestar.plugins.problem_details import (
        ProblemDetailsConfig,
        ProblemDetailsPlugin,
    )
    from litestar.static_files import create_static_files_router
    from litestar_granian import GranianPlugin
    from sqlalchemy.pool import StaticPool

    # Register tenant-scoping event handlers on SQLAlchemy.
    import novamoc.db._listeners  # noqa: F401
    from novamoc.api._problem_details import (
        make_litestar_validation_error_converter,
        make_msgspec_validation_error_converter,
        make_schema_error_converter,
        make_tenant_resolution_error_converter,
    )
    from novamoc.config import Settings, problem_html_dir
    from novamoc.domain.accounts import (
        AuthenticationMiddleware,
        TenantContextMiddleware,
        TenantResolutionError,
    )
    from novamoc.domain.events.controllers import EventsController
    from novamoc.domain.schema._errors import SchemaError
    from novamoc.domain.schema.controllers import SchemaController

    s = settings if settings is not None else Settings()

    engine_config = (
        EngineConfig(poolclass=StaticPool) if s.db.static_pool else EngineConfig()
    )
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string=s.db.url,
        # ty narrows the literal-arg type to ``Literal["autocommit", ...]``;
        # ``s.db.before_send_handler`` is a plain ``str`` from the
        # ``DatabaseSettings`` field, validated by advanced_alchemy at runtime.
        before_send_handler=s.db.before_send_handler,  # ty: ignore[invalid-argument-type]
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=s.db.create_all,
        engine_config=engine_config,
    )

    base_url = s.problem.docs_base_url
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: make_schema_error_converter(base_url),
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
        SQLAlchemyPlugin(config=alchemy_config),
        ProblemDetailsPlugin(config=problem_details_config),
    ]

    return Litestar(
        route_handlers=[SchemaController, EventsController, problem_docs_router],
        middleware=[
            DefineMiddleware(
                AuthenticationMiddleware,
                exclude=r"^/(openapi|problems)",
            ),
            TenantContextMiddleware(),
        ],
        plugins=plugins,
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
