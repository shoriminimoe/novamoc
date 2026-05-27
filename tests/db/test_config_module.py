"""Smoke tests for ``novamoc.db.config`` — the module the alchemy CLI resolves."""

from __future__ import annotations

import pytest
from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)

from novamoc.asgi import create_app
from novamoc.config import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    ServerSettings,
    Settings,
)
from novamoc.db.config import alchemy_config, build_alchemy_config


@pytest.mark.no_tenant
def test_alchemy_config_is_resolvable_via_dotted_path() -> None:
    """The CLI's ``--config novamoc.db.config.alchemy_config`` must resolve."""
    assert isinstance(alchemy_config, SQLAlchemyAsyncConfig)


@pytest.mark.no_tenant
def test_build_alchemy_config_uses_settings_url() -> None:
    """``build_alchemy_config`` must thread the settings URL into the config."""
    settings = Settings(db=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"))
    cfg = build_alchemy_config(settings)

    assert cfg.connection_string == "sqlite+aiosqlite:///:memory:"


@pytest.mark.no_tenant
def test_create_app_accepts_injected_alchemy_config() -> None:
    """The test seam: ``create_app`` must accept a pre-built config."""
    settings = Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:///:memory:",
            static_pool=True,
            create_all=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test"),
        auth=AuthSettings(session_cookie_secure=False),
    )
    injected = build_alchemy_config(settings)
    app = create_app(settings=settings, alchemy_config=injected)

    plugin = app.plugins.get(SQLAlchemyPlugin)
    plugin_cfg = next(c for c in plugin.config if isinstance(c, SQLAlchemyAsyncConfig))
    assert plugin_cfg is injected
