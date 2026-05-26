"""Smoke tests for ``novamoc.db.config`` — the module the alchemy CLI resolves."""

from __future__ import annotations

import pytest
from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from novamoc.config import DatabaseSettings, Settings
from novamoc.db.config import alchemy_config, build_alchemy_config


@pytest.mark.no_tenant
def test_alchemy_config_is_resolvable_via_dotted_path() -> None:
    """The CLI's ``--config novamoc.db.config:alchemy_config`` must resolve."""
    assert isinstance(alchemy_config, SQLAlchemyAsyncConfig)


@pytest.mark.no_tenant
def test_build_alchemy_config_uses_settings_url() -> None:
    """``build_alchemy_config`` must thread the settings URL into the config."""
    settings = Settings(db=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"))
    cfg = build_alchemy_config(settings)

    assert cfg.connection_string == "sqlite+aiosqlite:///:memory:"
