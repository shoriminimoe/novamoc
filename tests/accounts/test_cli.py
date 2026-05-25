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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.base import metadata_registry
from click.testing import CliRunner
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the models registers their tables on the shared metadata
# registry so ``create_all`` below picks them up.
import novamoc.db.models  # noqa: F401
from novamoc.cli import main
from novamoc.db.models._auth import Session, User
from novamoc.domain.accounts._password import PasswordHasher

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


def test_user_set_password_persists_new_hash(runner: CliRunner, db_url: str) -> None:
    """The new hash actually persists — a missing flush/commit would regress this."""
    runner.invoke(main, ["user", "create", "alice", "--password", "old"])
    result = runner.invoke(main, ["user", "set-password", "alice", "--password", "new"])
    assert result.exit_code == 0, (result.output, result.stderr)

    async def _hash() -> str:
        eng = create_async_engine(db_url)
        try:
            async with eng.connect() as conn:
                row = (
                    await conn.execute(
                        select(User.__table__.c.password_hash).where(
                            User.__table__.c.username == "alice"
                        )
                    )
                ).one()
                return row[0]
        finally:
            await eng.dispose()

    stored = asyncio.run(_hash())
    hasher = PasswordHasher()
    assert hasher.verify(stored, "new") is True
    assert hasher.verify(stored, "old") is False


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


def test_auth_gc_sessions_deletes_only_expired(
    runner: CliRunner, db_url: str
) -> None:
    """Seed one expired and one live session; only the expired row is deleted."""

    async def _seed() -> tuple[uuid.UUID, uuid.UUID]:
        eng = create_async_engine(db_url)
        try:
            async with eng.begin() as conn:
                now = datetime.now(UTC)
                expired_id = uuid.uuid4()
                live_id = uuid.uuid4()
                await conn.execute(
                    insert(Session).values(
                        id=expired_id,
                        session_id="expired-sid",
                        data=b"",
                        expires_at=now - timedelta(hours=1),
                    )
                )
                await conn.execute(
                    insert(Session).values(
                        id=live_id,
                        session_id="live-sid",
                        data=b"",
                        expires_at=now + timedelta(hours=1),
                    )
                )
                return expired_id, live_id
        finally:
            await eng.dispose()

    expired_id, live_id = asyncio.run(_seed())

    result = runner.invoke(main, ["auth", "gc-sessions"])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "Deleted 1 expired sessions." in result.stdout

    async def _remaining() -> list[uuid.UUID]:
        eng = create_async_engine(db_url)
        try:
            async with eng.connect() as conn:
                rows = await conn.execute(select(Session.__table__.c.id))
                return [r[0] for r in rows.all()]
        finally:
            await eng.dispose()

    remaining = asyncio.run(_remaining())
    assert expired_id not in remaining
    assert live_id in remaining


# ---------------------------------------------------------------------------
# Empty-string rejection ([2] / [8] in the PR #115 review)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["", "   ", "\t\n"])
def test_user_create_empty_password_exits_nonzero(
    runner: CliRunner, db_url: str, password: str
) -> None:
    result = runner.invoke(main, ["user", "create", "alice", "--password", password])
    assert result.exit_code != 0
    assert "password" in result.stderr.lower()


@pytest.mark.parametrize("password", ["", "   ", "\t\n"])
def test_user_set_password_empty_password_exits_nonzero(
    runner: CliRunner, db_url: str, password: str
) -> None:
    runner.invoke(main, ["user", "create", "alice", "--password", "old"])
    result = runner.invoke(
        main, ["user", "set-password", "alice", "--password", password]
    )
    assert result.exit_code != 0
    assert "password" in result.stderr.lower()


@pytest.mark.parametrize("display_name", ["", "   ", "\t\n"])
def test_tenant_create_empty_display_name_exits_nonzero(
    runner: CliRunner, db_url: str, display_name: str
) -> None:
    result = runner.invoke(main, ["tenant", "create", "--display-name", display_name])
    assert result.exit_code != 0
    assert (
        "display-name" in result.stderr.lower()
        or "display_name" in result.stderr.lower()
    )


# ---------------------------------------------------------------------------
# Settings parse-error mapping ([5] in the PR #115 review)
# ---------------------------------------------------------------------------


def test_settings_parse_error_renders_as_clickexception(
    runner: CliRunner, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad env-var value exits with a friendly message, not a raw traceback."""
    monkeypatch.setenv("NOVAMOC_AUTH_ARGON2_TIME_COST", "not-an-int")
    result = runner.invoke(main, ["user", "create", "alice", "--password", "x"])
    assert result.exit_code != 0
    # Friendly message includes the offending env var; raw ValueError tracebacks
    # would not appear in click's stderr formatting.
    assert "NOVAMOC_AUTH_ARGON2_TIME_COST" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# Missing tenant on add-to-tenant ([1] in the PR #115 review)
# ---------------------------------------------------------------------------


def test_user_add_to_tenant_unknown_tenant_exits_nonzero(
    runner: CliRunner, db_url: str
) -> None:
    """FK PRAGMA is not wired yet; an explicit lookup must catch a phantom UUID."""
    runner.invoke(main, ["user", "create", "alice", "--password", "x"])
    phantom = uuid.uuid4()
    result = runner.invoke(main, ["user", "add-to-tenant", "alice", str(phantom)])
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()
    assert str(phantom) in result.stderr


# ---------------------------------------------------------------------------
# Echoed username uses the folded form ([9] in the PR #115 review)
# ---------------------------------------------------------------------------


def test_user_create_echoes_folded_username(runner: CliRunner, db_url: str) -> None:
    result = runner.invoke(main, ["user", "create", "ALICE", "--password", "x"])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "ALICE" not in result.stdout
    assert "alice" in result.stdout


def test_user_set_password_echoes_folded_username(
    runner: CliRunner, db_url: str
) -> None:
    runner.invoke(main, ["user", "create", "alice", "--password", "old"])
    result = runner.invoke(main, ["user", "set-password", "ALICE", "--password", "new"])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "ALICE" not in result.stdout
    assert "alice" in result.stdout


def test_user_add_to_tenant_echoes_folded_username(
    runner: CliRunner, db_url: str
) -> None:
    tenant_res = runner.invoke(main, ["tenant", "create", "--display-name", "Acme"])
    tenant_id = _extract_uuid(tenant_res.stdout)
    runner.invoke(main, ["user", "create", "alice", "--password", "x"])
    result = runner.invoke(main, ["user", "add-to-tenant", "ALICE", str(tenant_id)])
    assert result.exit_code == 0, (result.output, result.stderr)
    assert "ALICE" not in result.stdout
    assert "alice" in result.stdout


# ---------------------------------------------------------------------------
# user exists exit-code semantics ([7] in the PR #115 review)
# ---------------------------------------------------------------------------


def test_user_exists_returns_two_on_db_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exit 2 distinguishes 'CLI errored' from 'user absent' (exit 1)."""
    # Point at a directory that exists but a path that is the directory itself,
    # so the SQLite connection cannot open it.
    bad_url = f"sqlite+aiosqlite:///{tmp_path}"
    monkeypatch.setenv("NOVAMOC_DB_URL", bad_url)
    result = runner.invoke(main, ["user", "exists", "ghost"])
    assert result.exit_code == 2, (result.exit_code, result.output, result.stderr)
