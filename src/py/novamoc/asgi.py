from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar


def create_app() -> Litestar:
    """Create the ASGI app."""

    import msgspec
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.exceptions import ValidationException
    from litestar.openapi.config import OpenAPIConfig
    from litestar.plugins.problem_details import (
        ProblemDetailsConfig,
        ProblemDetailsPlugin,
    )
    from litestar_granian import GranianPlugin

    from novamoc.api._problem_details import (
        litestar_validation_error_to_problem_details,
        msgspec_validation_error_to_problem_details,
        schema_error_to_problem_details,
    )
    from novamoc.domain.schema._errors import SchemaError
    from novamoc.domain.schema.controllers import SchemaController

    session_config = AsyncSessionConfig(expire_on_commit=False)
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///test.sqlite",
        before_send_handler="autocommit",
        session_config=session_config,
        create_all=True,
    )

    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: schema_error_to_problem_details,
            msgspec.ValidationError: msgspec_validation_error_to_problem_details,
            ValidationException: litestar_validation_error_to_problem_details,
        },
    )

    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            GranianPlugin(),
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
