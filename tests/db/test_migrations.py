"""Tests for the on-disk Alembic migration tree."""

from __future__ import annotations

from importlib.resources import files

import pytest

from novamoc.db.config import alchemy_config


@pytest.mark.no_tenant
def test_migrations_dir_resolves_via_importlib_resources() -> None:
    """The Alembic script location must resolve in both wheel and editable installs."""
    migrations = files("novamoc.db") / "migrations"
    assert migrations.is_dir()
    assert (migrations / "env.py").is_file()
    assert (migrations / "script.py.mako").is_file()
    assert (migrations / "versions").is_dir()


@pytest.mark.no_tenant
def test_alchemy_config_advertises_the_migrations_dir() -> None:
    assert alchemy_config.alembic_config is not None
    assert alchemy_config.alembic_config.script_location.endswith("migrations")


@pytest.mark.no_tenant
def test_baseline_revision_exists() -> None:
    """A baseline revision must exist; the bootstrap contract demands a HEAD."""
    versions = files("novamoc.db") / "migrations" / "versions"
    revisions = [
        p
        for p in versions.iterdir()
        if p.name.endswith(".py") and p.name != "__init__.py"
    ]
    assert revisions, "no baseline revision found under migrations/versions/"
