"""Tests for the ``novamoc`` operator CLI (M5.13).

The CLI builds its own engine + session from ``Settings()`` and runs
outside the request lifecycle, so each test points
``NOVAMOC_DB_URL`` at a per-test SQLite file via ``monkeypatch`` and
seeds the schema via ``metadata.create_all``. The CLI commands are
the production bootstrap path (init container / ``just bootstrap-dev``);
these tests pin the contract those scripts depend on.

The auth-registry tables (``users``, ``tenants``,
``user_tenant_memberships``, ``sessions``) are not tenant-scoped, so
the autouse tenant fixture has nothing to do here — every test in
this module opts out via ``no_tenant``.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.base import metadata_registry
from click.testing import CliRunner
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the models registers their tables on the shared metadata
# registry so ``create_all`` below picks them up.
import novamoc.db.models  # noqa: F401
from novamoc.cli import main

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.no_tenant


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``NOVAMOC_DB_URL`` at a per-test SQLite file and seed schema.

    Returns the URL so individual tests can assert against the same DB
    directly if they need to. The CLI reads ``Settings()`` on every
    invocation, so setting the env var via ``monkeypatch`` is enough to
    redirect it.
    """
    path = tmp_path / "novamoc.sqlite"
    url = f"sqlite+aiosqlite:///{path}"
    monkeypatch.setenv("NOVAMOC_DB_URL", url)

    async def _create() -> None:
        eng = create_async_engine(url)
        try:
            async with eng.begin() as conn:
                for key in metadata_registry:
                    await conn.run_sync(metadata_registry[key].create_all)
        finally:
            await eng.dispose()

    asyncio.run(_create())
    return url


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.3 removed the ``mix_stderr`` knob — stdout/stderr are
    # separate by default, which is the behaviour the assertions below
    # rely on (e.g. ``user exists`` must produce empty stdout).
    return CliRunner()


_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _extract_uuid(text: str) -> uuid.UUID:
    match = _UUID_RE.search(text)
    assert match is not None, f"no UUID found in {text!r}"
    return uuid.UUID(match.group(0))


def test_help_lists_groups(runner: CliRunner) -> None:
    """``novamoc --help`` enumerates the three sub-groups."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0, result.output
    for group in ("tenant", "user", "auth"):
        assert group in result.output


def test_tenant_create_prints_uuid(runner: CliRunner, db_url: str) -> None:
    result = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert result.stdout.startswith("Created tenant ")
    # Parseable UUID at the end of the output — what the recipe will awk for.
    _extract_uuid(result.stdout)


def test_user_create_succeeds(runner: CliRunner, db_url: str) -> None:
    result = runner.invoke(
        main, ["user", "create", "alice", "--password", "correct horse"]
    )
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "alice" in result.stdout.lower()


def test_user_create_duplicate_exits_nonzero(runner: CliRunner, db_url: str) -> None:
    first = runner.invoke(main, ["user", "create", "alice", "--password", "x"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(main, ["user", "create", "alice", "--password", "y"])
    assert second.exit_code != 0
    assert "already exists" in second.stderr.lower()
    assert "alice" in second.stderr.lower()


def test_user_set_password_succeeds(runner: CliRunner, db_url: str) -> None:
    runner.invoke(main, ["user", "create", "alice", "--password", "old"])

    result = runner.invoke(main, ["user", "set-password", "alice", "--password", "new"])
    assert result.exit_code == 0, (result.output, result.stderr)


def test_user_set_password_missing_user_exits_nonzero(
    runner: CliRunner, db_url: str
) -> None:
    result = runner.invoke(main, ["user", "set-password", "ghost", "--password", "x"])
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()
    assert "ghost" in result.stderr.lower()


def test_user_exists_returns_zero_after_create(runner: CliRunner, db_url: str) -> None:
    runner.invoke(main, ["user", "create", "alice", "--password", "x"])

    result = runner.invoke(main, ["user", "exists", "alice"])
    assert result.exit_code == 0
    # No stdout output — only the exit code is the contract.
    assert result.stdout == ""


def test_user_exists_returns_one_for_missing(runner: CliRunner, db_url: str) -> None:
    result = runner.invoke(main, ["user", "exists", "ghost"])
    assert result.exit_code == 1
    assert result.stdout == ""


def test_user_add_to_tenant_succeeds(runner: CliRunner, db_url: str) -> None:
    tenant_res = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    tenant_id = _extract_uuid(tenant_res.stdout)

    runner.invoke(main, ["user", "create", "alice", "--password", "x"])

    result = runner.invoke(main, ["user", "add-to-tenant", "alice", str(tenant_id)])
    assert result.exit_code == 0, (result.output, result.stderr)


def test_user_add_to_tenant_invalid_uuid_exits_nonzero(
    runner: CliRunner, db_url: str
) -> None:
    runner.invoke(main, ["user", "create", "alice", "--password", "x"])

    result = runner.invoke(main, ["user", "add-to-tenant", "alice", "not-a-uuid"])
    assert result.exit_code != 0
    assert "not a valid uuid" in result.stderr.lower()


def test_user_add_to_tenant_missing_user_exits_nonzero(
    runner: CliRunner, db_url: str
) -> None:
    tenant_res = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    tenant_id = _extract_uuid(tenant_res.stdout)

    result = runner.invoke(main, ["user", "add-to-tenant", "ghost", str(tenant_id)])
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()


def test_user_add_to_tenant_already_has_tenant_exits_nonzero(
    runner: CliRunner, db_url: str
) -> None:
    """The N:1 invariant rejection — the CLI side of M5.4."""
    first = runner.invoke(main, ["tenant", "create", "--display-name", "Alpha"])
    first_tid = _extract_uuid(first.stdout)
    second = runner.invoke(main, ["tenant", "create", "--display-name", "Bravo"])
    second_tid = _extract_uuid(second.stdout)

    runner.invoke(main, ["user", "create", "alice", "--password", "x"])
    runner.invoke(main, ["user", "add-to-tenant", "alice", str(first_tid)])

    result = runner.invoke(main, ["user", "add-to-tenant", "alice", str(second_tid)])
    assert result.exit_code != 0
    assert re.search(r"already.*tenant", result.stderr, re.IGNORECASE)


def test_auth_gc_sessions_on_empty_table_prints_count(
    runner: CliRunner, db_url: str
) -> None:
    result = runner.invoke(main, ["auth", "gc-sessions"])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "Deleted 0 expired sessions." in result.stdout
