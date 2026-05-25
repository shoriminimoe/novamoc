"""Operator CLI exposed as the ``novamoc`` console script (M5.13).

The CLI is the only bootstrap path for tenants, users, and
memberships — production deployments run it in an init container,
local dev wires it through ``just bootstrap-dev`` (M5.15). Each
sub-command builds its own async engine + session from
``Settings()`` (so it picks up ``NOVAMOC_DB_URL`` and the auth
cost parameters at invocation time), runs the operation,
commits on success, rolls back and exits non-zero with a
human-readable stderr message on any failure.

Output convention: success messages on stdout, error messages on
stderr. The ``tenant create`` success line ends with the new
tenant's UUID so the M5.15 recipe can ``awk`` it out.

The CLI runs outside the request lifecycle so it does not use the
tenant-scoping middleware or contextvar. The auth-registry tables
are not tenant-scoped (they have no ``tenant_id`` column), so the
listeners short-circuit naturally. We still import the listeners
module so any future CLI command that touches a synced table goes
through the same structural enforcement as the web layer.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Register tenant-scoping event handlers on SQLAlchemy. Today's CLI
# commands only touch the non-scoped auth-registry tables so the
# listeners short-circuit, but importing here keeps the production
# CLI path aligned with ``asgi.create_app`` for any future command
# that touches a synced table.
import novamoc.db._listeners  # noqa: F401
from novamoc.config import Settings
from novamoc.db.models._auth import Session
from novamoc.domain.accounts._errors import UserAlreadyHasTenantError
from novamoc.domain.accounts._password import PasswordHasher
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession


def _password_hasher(settings: Settings) -> PasswordHasher:
    """Build a ``PasswordHasher`` from the configured auth parameters."""
    return PasswordHasher(
        time_cost=settings.auth.argon2_time_cost,
        memory_cost_kib=settings.auth.argon2_memory_cost_kib,
        parallelism=settings.auth.argon2_parallelism,
    )


async def _run_in_session[T](
    settings: Settings,
    work: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Run ``work`` inside a fresh ``AsyncSession``.

    Commits on success, rolls back on any exception (which then
    propagates to the caller for the click error mapping). The
    engine is disposed before returning so the CLI process exits
    cleanly. ``commit`` runs inside the same ``try`` as ``work`` so
    a commit-time failure (deferred constraint, future commit-hook)
    follows the explicit rollback path rather than relying on
    ``AsyncSession.close()``'s implicit rollback.
    """
    engine = create_async_engine(settings.db.url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            try:
                result = await work(session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            return result
    finally:
        await engine.dispose()


def _prompt_password_if_missing(password: str | None) -> str:
    """Prompt with hidden input when ``--password`` was not supplied.

    Confirmation is required so a typo at the operator console does
    not silently set an unrecoverable password.
    """
    if password is not None:
        return password
    return click.prompt("Password", hide_input=True, confirmation_prompt=True)


@click.group()
def main() -> None:
    """novaMOC operator CLI.

    Sub-groups:

    * ``tenant`` — tenant registry administration.
    * ``user`` — user registry administration.
    * ``auth`` — session / credential maintenance.
    """


# ---------------------------------------------------------------------------
# tenant
# ---------------------------------------------------------------------------


@main.group()
def tenant() -> None:
    """Tenant registry administration."""


@tenant.command("create")
@click.option(
    "--display-name", required=True, help="Human-readable name for the tenant."
)
def tenant_create(display_name: str) -> None:
    """Create a tenant and print its UUID."""
    settings = Settings()

    async def work(session: AsyncSession) -> uuid.UUID:
        # Return the UUID directly rather than handing back an ORM
        # instance whose attributes would be read after ``engine.dispose()``.
        svc = TenantService(session=session)
        created = await svc.create(
            data={"display_name": display_name}, auto_commit=False
        )
        return created.id

    created_id = asyncio.run(_run_in_session(settings, work))
    click.echo(f"Created tenant {created_id}.")


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------


@main.group()
def user() -> None:
    """User registry administration."""


@user.command("create")
@click.argument("username")
@click.option(
    "--password",
    default=None,
    help="Password for the new user. Prompts interactively when omitted.",
)
def user_create(username: str, password: str | None) -> None:
    """Create a user with a hashed password."""
    settings = Settings()
    hasher = _password_hasher(settings)
    plaintext = _prompt_password_if_missing(password)
    hashed = hasher.hash(plaintext)

    async def work(session: AsyncSession) -> None:
        svc = UserService(session=session)
        # Pre-check: the service folds usernames at create-time, so a
        # case-folded lookup catches duplicates before SQLAlchemy raises
        # IntegrityError. The UNIQUE constraint on ``users.username``
        # remains the structural backstop.
        existing = await svc.get_by_username(username)
        if existing is not None:
            msg = f"User '{username}' already exists."
            raise click.ClickException(msg)
        await svc.create(
            data={"username": username, "password_hash": hashed},
            auto_commit=False,
        )

    asyncio.run(_run_in_session(settings, work))
    click.echo(f"Created user {username}.")


@user.command("set-password")
@click.argument("username")
@click.option(
    "--password",
    default=None,
    help="New password. Prompts interactively when omitted.",
)
def user_set_password(username: str, password: str | None) -> None:
    """Reset ``<username>``'s password.

    Operator-driven: no email-confirmation flow in v1. The new hash
    uses the current cost parameters from :class:`AuthSettings`.
    """
    settings = Settings()
    hasher = _password_hasher(settings)
    plaintext = _prompt_password_if_missing(password)
    hashed = hasher.hash(plaintext)

    async def work(session: AsyncSession) -> None:
        svc = UserService(session=session)
        existing = await svc.get_by_username(username)
        if existing is None:
            msg = f"User '{username}' not found."
            raise click.ClickException(msg)
        existing.password_hash = hashed
        # No explicit flush — ``_run_in_session`` commits, which
        # flushes implicitly.

    asyncio.run(_run_in_session(settings, work))
    click.echo(f"Password updated for user {username}.")


@user.command("exists")
@click.argument("username")
def user_exists(username: str) -> None:
    """Exit 0 if ``<username>`` exists, 1 otherwise.

    Produces no stdout output — the contract is the exit code. Used
    by ``just bootstrap-dev`` (M5.15) to skip the seed when the
    target user is already provisioned.
    """
    settings = Settings()

    async def work(session: AsyncSession) -> bool:
        svc = UserService(session=session)
        return (await svc.get_by_username(username)) is not None

    found = asyncio.run(_run_in_session(settings, work))
    if not found:
        sys.exit(1)


@user.command("add-to-tenant")
@click.argument("username")
@click.argument("tenant_uuid")
def user_add_to_tenant(username: str, tenant_uuid: str) -> None:
    """Add ``<username>`` to ``<tenant-uuid>`` as a membership.

    The N:1 invariant (ADR-020, v1) is enforced by
    :class:`UserTenantMembershipService`; the CLI surfaces that
    rejection as a non-zero exit with a message containing
    "already" and "tenant".
    """
    try:
        tenant_id = uuid.UUID(tenant_uuid)
    except ValueError:
        msg = f"'{tenant_uuid}' is not a valid UUID."
        raise click.ClickException(msg) from None

    settings = Settings()

    async def work(session: AsyncSession) -> None:
        users = UserService(session=session)
        target = await users.get_by_username(username)
        if target is None:
            msg = f"User '{username}' not found."
            raise click.ClickException(msg)
        memberships = UserTenantMembershipService(session=session)
        try:
            await memberships.create(
                data={"user_id": target.id, "tenant_id": tenant_id},
                auto_commit=False,
            )
        except UserAlreadyHasTenantError as exc:
            # Surface the friendly rejection as a CLI failure. Keeping
            # both "already" and "tenant" in the message lets the M5.15
            # bootstrap recipe (and the test) grep for the N:1 case
            # without coupling to the full sentence.
            msg = f"User '{username}' already belongs to a tenant."
            raise click.ClickException(msg) from exc

    asyncio.run(_run_in_session(settings, work))
    click.echo(f"Added user {username} to tenant {tenant_id}.")


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


@main.group()
def auth() -> None:
    """Session / credential maintenance."""


@auth.command("gc-sessions")
def auth_gc_sessions() -> None:
    """Delete expired ``sessions`` rows and print the count.

    Opportunistic GC; the design records a future scheduler as tech
    debt (ADR-020). Operators invoke this on a cadence appropriate
    to their session TTL.
    """
    settings = Settings()

    async def work(session: AsyncSession) -> int:
        now = datetime.now(UTC)
        table = Session.__table__
        stmt = delete(table).where(table.c.expires_at < now)  # ty: ignore[invalid-argument-type]
        result = await session.execute(stmt)
        # ``Result.rowcount`` is reliable for DELETE on SQLite under
        # SQLAlchemy 2.x; the few backends that mark it ``-1`` for
        # bulk DML do not include the dialects this project targets.
        # The static type is ``Result[Any]`` (the typed base), which
        # does not expose ``rowcount`` — the attribute lives on
        # ``CursorResult``. The same pattern in
        # ``domain/events/_row_state.py`` survives ty because the
        # ``session`` there is unannotated; here we keep the annotation
        # and accept the narrow ignore.
        return result.rowcount or 0  # ty: ignore[unresolved-attribute]

    deleted = asyncio.run(_run_in_session(settings, work))
    click.echo(f"Deleted {deleted} expired sessions.")
