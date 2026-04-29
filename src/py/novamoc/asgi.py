from __future__ import annotations
from typing import TYPE_CHECKING
from litestar import get

if TYPE_CHECKING:
    from litestar import Litestar


def create_app() -> Litestar:
    """Create ASGI app"""

    from litestar import Litestar
    from litestar_granian import GranianPlugin
    from advanced_alchemy.extensions.litestar import (
        AsyncSessionConfig,
        SQLAlchemyAsyncConfig,
        SQLAlchemyPlugin,
    )

    session_config = AsyncSessionConfig(expire_on_commit=False)
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///test.sqlite",
        before_send_handler="autocommit",
        session_config=session_config,
        create_all=True,
    )

    return Litestar(
        route_handlers=[
            hello_world,
        ],
        plugins=[
            GranianPlugin(),
            SQLAlchemyPlugin(config=alchemy_config),
        ],
    )
