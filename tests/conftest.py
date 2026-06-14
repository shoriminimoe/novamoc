"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.alembic.commands import AlembicCommands
from advanced_alchemy.base import metadata_registry
from advanced_alchemy.extensions.litestar import (
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar.testing import AsyncTestClient
from render_problem_docs import _default_src_dir, _default_titles, render_all
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

# Importing the listeners registers tenant-scoping event handlers on SQLAlchemy.
import novamoc.db._listeners

# Importing the models registers their tables on the shared metadata registry.
import novamoc.db.models  # noqa: F401
from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.asgi import create_app
from novamoc.config import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    ServerSettings,
    Settings,
    problem_html_dir,
)
from novamoc.db._pragmas import register_sqlite_pragmas
from novamoc.db._tenant_context import use_tenant
from novamoc.db.config import build_alchemy_config
from novamoc.db.models._auth import Tenant
from novamoc.domain.accounts._services import (
    TenantService,
    UserService,
    UserTenantMembershipService,
)
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)
from tests._constants import DEV_PASSWORD, DEV_TENANT_ID, DEV_USERNAME
from tests.data.loader import load_scenario

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
    from uuid import UUID

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
    )

    from tests.data.scenarios import Scenario


@pytest.fixture(autouse=True)
def tenant(request: pytest.FixtureRequest) -> Iterator[UUID | None]:
    """Set the storage-layer tenant contextvar for every test's duration.

    Autouse so tests don't need to declare ``tenant`` purely to get a
    contextvar; defaults to :data:`tests._constants.DEV_TENANT_ID`. Tests
    that need a specific tenant value (or want to flip across tenants)
    override via indirect parametrization, declaring ``tenant: UUID``
    only when they actually read the value:

        @pytest.mark.parametrize(
            "tenant", [DEV_TENANT_ID_A, DEV_TENANT_ID_B], indirect=True,
        )
        async def test_cross_tenant(tenant: UUID): ...

    Tests that must run with no tenant context (to assert the fail-closed
    paths in the listeners or to verify the contextvar primitive itself)
    opt out with the ``no_tenant`` marker:

        @pytest.mark.no_tenant
        async def test_unscoped_select_raises(): ...
    """
    if request.node.get_closest_marker("no_tenant"):
        yield None
        return
    tenant_id = getattr(request, "param", DEV_TENANT_ID)
    with use_tenant(tenant_id):
        yield tenant_id


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Pragma parity with production engines built via build_alchemy_config:
    # the `app` fixture and `tests/db/test_pragmas.py` already go through
    # that path; the direct-DB `engine` fixture skips it (no Alembic, no
    # tenant-scoping wrap needed for storage-layer tests) but still wants
    # the same connect-time pragmas. Tests that need different pragmas
    # build their own engine inline instead of using this fixture.
    register_sqlite_pragmas(eng)
    async with eng.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        try:
            yield s
        finally:
            await s.rollback()


@pytest.fixture
def services(session) -> ServiceBundle:
    return ServiceBundle(
        asset_type=AssetTypeService(session=session),
        asset_type_field=AssetTypeFieldService(session=session),
        maintenance_record_type=MaintenanceRecordTypeService(session=session),
        maintenance_record_type_field=MaintenanceRecordTypeFieldService(
            session=session
        ),
        change_log=SchemaChangeLogService(session=session),
    )


@pytest.fixture
def seed(
    session: AsyncSession,
    services: ServiceBundle,
) -> Callable[..., Awaitable[Mapping[str, Mapping[str, UUID]]]]:
    """Return an async ``seed(scenario[, tenant_id=...])`` callable.

    Wraps ``tests.data.loader.load_scenario`` with the per-test ``session``
    and ``services`` fixtures so test bodies stay focused on assertions:

        from tests.data.scenarios import ACTIVE_TRUCK

        async def test_x(seed, services):
            ids = await seed(ACTIVE_TRUCK)
            truck_id = ids["asset_type"]["Truck"]

    When ``tenant_id`` is supplied the scenario is loaded under that tenant
    regardless of the ambient ``tenant`` fixture, which is useful for
    cross-tenant isolation tests that seed the same scenario twice:

        a_ids = await seed(ACTIVE_TRUCK, tenant_id=DEV_TENANT_ID_A)
        b_ids = await seed(ACTIVE_TRUCK, tenant_id=DEV_TENANT_ID_B)
    """

    async def _seed(
        scenario: Scenario,
        tenant_id: UUID | None = None,
    ) -> Mapping[str, Mapping[str, UUID]]:
        if tenant_id is not None:
            with use_tenant(tenant_id):
                return await load_scenario(scenario, session=session, services=services)
        return await load_scenario(scenario, session=session, services=services)

    return _seed


@pytest.fixture
def settings() -> Settings:
    """Test-time ``Settings`` literal used by the ``app`` fixture.

    All fields are explicit so the test app's behaviour does not depend on
    ambient env-var state. ``StaticPool`` keeps the in-memory SQLite engine
    on a single connection so the request-scoped session, the autocommit
    handler, and any background fold see the same database.

    ``AuthSettings`` uses the weakened argon2id parameters from
    ``tests.accounts.test_handlers._FAST`` so login round-trips stay
    sub-second; ``session_cookie_secure=False`` lets ``AsyncTestClient``
    (which uses ``http://`` URLs) round-trip the cookie.
    """
    return Settings(
        db=DatabaseSettings(
            url="sqlite+aiosqlite:///:memory:",
            static_pool=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test", broadcaster_enabled=False),
        auth=AuthSettings(
            argon2_time_cost=1,
            argon2_memory_cost_kib=8192,
            argon2_parallelism=1,
            session_cookie_secure=False,
        ),
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Litestar]:
    """A Litestar app over a freshly-built in-memory SQLite.

    Builds the engine in the conftest, runs ``metadata.create_all``
    against it (the same loop the ``engine`` fixture uses), and stamps
    the Alembic HEAD so the app's startup gate accepts the database.
    The pre-built ``SQLAlchemyAsyncConfig`` is handed to ``create_app``
    via the documented ``alchemy_config`` keyword so the plugin uses
    the populated engine instead of opening a fresh one.
    """
    alchemy_config = build_alchemy_config(settings)
    engine = alchemy_config.get_engine()
    async with engine.begin() as conn:
        for key in metadata_registry:
            await conn.run_sync(metadata_registry[key].create_all)
    # ``AlembicCommands.stamp`` is sync but its env.py calls
    # ``asyncio.run(run_migrations_online())`` internally; calling it
    # from a running event loop raises ``RuntimeError: asyncio.run()
    # cannot be called from a running event loop``. ``to_thread``
    # gives env.py a fresh loop on a worker thread.
    await asyncio.to_thread(AlembicCommands(alchemy_config).stamp, "head")
    try:
        yield create_app(settings=settings, alchemy_config=alchemy_config)
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class DevAdmin:
    """Credentials for the canonical admin user the e2e tests log in as.

    Tests use :func:`seed_dev_admin` to write the matching user row
    into a running app, then post these credentials to ``/auth/login``.
    """

    username: str
    password: str
    tenant_id: UUID


_DEV_ADMIN = DevAdmin(
    username=DEV_USERNAME,
    password=DEV_PASSWORD,
    tenant_id=DEV_TENANT_ID,
)


async def seed_dev_admin(app: Litestar) -> None:
    """Seed the canonical admin tenant + user + membership into ``app``.

    Call **inside** a live ``AsyncTestClient`` context — the plugin's
    lifespan startup must have run so the registry tables exist. We
    use ``alchemy_config.get_session()`` (the advanced-alchemy
    documented helper for code outside the request lifecycle) since
    seeding is not request-scoped. The ``tenant_id`` is pinned to
    :data:`DEV_TENANT_ID` so every test sees the same value on
    ``request.auth.tenant_id``; the production CLI never pins a
    specific UUID (the fixture is the only place that does, and
    that's deliberate — scenarios reference the same constant and
    need a deterministic value across runs).
    """
    plugin = app.plugins.get(SQLAlchemyPlugin)
    alchemy_config = next(
        c for c in plugin.config if isinstance(c, SQLAlchemyAsyncConfig)
    )
    hasher = app.state.password_hasher

    async with alchemy_config.get_session() as db_session:
        tenants = TenantService(session=db_session)
        users = UserService(session=db_session)
        memberships = UserTenantMembershipService(session=db_session)

        # Pin the tenant UUID via repository.add: TenantService.create
        # would let advanced_alchemy assign a fresh UUIDv7. Tests need
        # the deterministic DEV_TENANT_ID for cross-fixture consistency.
        tenant = Tenant(id=DEV_TENANT_ID, display_name="Acme")
        await tenants.repository.add(tenant)
        user = await users.create(
            data={
                "username": DEV_USERNAME,
                "password_hash": hasher.hash(DEV_PASSWORD),
            },
            auto_commit=False,
        )
        await memberships.create(
            data={"user_id": user.id, "tenant_id": tenant.id},
            auto_commit=False,
        )
        await db_session.commit()


@pytest.fixture
def dev_admin() -> DevAdmin:
    """The canonical admin credentials. Pair with :func:`seed_dev_admin`."""
    return _DEV_ADMIN


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient]:
    """An authenticated ``AsyncTestClient``.

    Enters the ``AsyncTestClient`` context (the plugin's lifespan
    fires and ``session_maker`` lands on state; the ``app`` fixture
    has already created the tables and stamped Alembic HEAD), seeds
    the admin, then logs in. ``httpx`` persists the session cookie
    across subsequent requests, so the rest of the test runs as the
    seeded admin. Tests exercising the rejection path use
    :func:`unauth_client` instead.
    """
    async with AsyncTestClient(app) as c:
        await seed_dev_admin(app)
        resp = await c.post(
            "/auth/login",
            json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
        )
        assert resp.status_code == 204, resp.text
        yield c


@pytest.fixture
async def unauth_client(app: Litestar) -> AsyncIterator[AsyncTestClient]:
    """An ``AsyncTestClient`` with no session — used by 401 rejection tests."""
    async with AsyncTestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _render_problem_html() -> None:
    """Render per-code HTML before any test boots the app.

    Tests run in editable-install mode where uv_build's wheel data is
    not materialized, so ``problem_html_dir()`` resolves to the
    build-artifact fallback at ``build/wheel_data/novamoc/html/``.
    Rendering there keeps the test path identical to the dev workflow
    driven by ``just render-problem-docs``.
    """
    render_all(
        src_dir=_default_src_dir(),
        out_dir=problem_html_dir(),
        expected_codes=PROBLEM_CODES,
        titles=_default_titles(),
    )
