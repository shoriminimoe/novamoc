"""Smoke tests for ``AuthController`` (M5.10, issue #91).

Verifies the controller class registers cleanly on a ``Litestar`` app
and that the three routes mount at the expected paths. The e2e wire
coverage (real cookies, real session middleware, real bodies) lives in
M5.12 and depends on the session middleware that lands in M5.11.
"""

from __future__ import annotations

from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar import Litestar
from litestar.datastructures import State

from novamoc.config import Settings
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts.controllers import AuthController


def test_controller_registers_on_app() -> None:
    """``AuthController`` mounts on a stock Litestar without errors."""
    settings = Settings()
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///:memory:",
        create_all=False,
    )
    app = Litestar(
        route_handlers=[AuthController],
        plugins=[SQLAlchemyPlugin(config=alchemy_config)],
        state=State(
            {
                "settings": settings,
                "password_hasher": PasswordHasher.from_defaults(),
            }
        ),
    )

    paths = {route.path for route in app.routes}
    assert "/auth/login" in paths
    assert "/auth/logout" in paths
    assert "/auth/me" in paths
