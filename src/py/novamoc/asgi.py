from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar


def create_app() -> Litestar:
    """Create the ASGI app."""

    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )
    from litestar import Litestar
    from litestar.openapi.config import OpenAPIConfig
    from litestar_granian import GranianPlugin

    from novamoc.domain.schema.controllers import SchemaController

    session_config = AsyncSessionConfig(expire_on_commit=False)
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///test.sqlite",
        before_send_handler="autocommit",
        session_config=session_config,
        create_all=True,
    )

    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            GranianPlugin(),
            SQLAlchemyPlugin(config=alchemy_config),
        ],
        # Default Litestar OpenAPI mount is /schema; move it so it doesn't
        # collide with our POST /schema route.
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )
