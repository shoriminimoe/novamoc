"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.base import metadata_registry
from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
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
from novamoc.db._tenant_context import use_tenant
from novamoc.db.models._auth import Tenant
from novamoc.domain.accounts._middleware import pick_async_alchemy_config
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
            create_all=True,
            before_send_handler="autocommit",
        ),
        server=ServerSettings(granian=False),
        app=AppSettings(docs_base_url="http://test"),
        auth=AuthSettings(
            argon2_time_cost=1,
            argon2_memory_cost_kib=8192,
            argon2_parallelism=1,
            session_cookie_secure=False,
        ),
    )


@pytest.fixture
async def app(settings: Settings) -> Litestar:
    """A Litestar app with an in-memory SQLite for e2e tests.

    Built via ``create_app(settings=...)`` so production and test paths
    share the same wiring; the per-test ``settings`` fixture supplies an
    explicit ``StaticPool`` in-memory DB and the ``http://test`` problem-
    docs base URL the e2e assertions key off.
    """
    return create_app(settings=settings)


@dataclass(frozen=True, slots=True)
class DevAdmin:
    """Identity of the seeded admin user the ``client`` fixture logs in as.

    Tests that need to assert the seeded user's UUID (e.g. the
    ``GET /auth/me`` response) declare ``dev_admin`` and read
    ``dev_admin.user_id`` directly. The credentials live in
    :mod:`tests._constants` and are the single source of truth.
    """

    username: str
    password: str
    user_id: UUID
    tenant_id: UUID


@pytest.fixture
async def dev_admin(app: Litestar) -> DevAdmin:
    """Seed the canonical admin user + tenant + membership.

    Mirrors what ``just bootstrap-dev`` (M5.15) will run on the CLI
    side but pins ``tenant_id = DEV_TENANT_ID`` so every e2e test sees
    the same tenant on ``request.auth.tenant_id``. The CLI never pins
    a specific tenant UUID — the test fixture is the only place that
    does, and that's deliberate: scenarios reference the same UUID
    constant and need a deterministic value across runs.

    Runs *before* ``AsyncTestClient``'s lifespan startup; we call
    ``create_all_metadata`` directly (the same helper the plugin's
    startup hook fires) so the registry writes have tables to land
    in. ``CREATE TABLE IF NOT EXISTS`` makes the lifespan re-run a
    no-op.
    """
    alchemy_config = pick_async_alchemy_config(app.plugins.get(SQLAlchemyPlugin))
    await alchemy_config.create_all_metadata(app)

    # Reuse the ``PasswordHasher`` ``create_app`` stashed on
    # ``app.state`` — it was built from the test ``settings``
    # ``AuthSettings`` cost params, so a local rebuild would be
    # identical bytes for more allocation.
    hasher = app.state.password_hasher

    async with alchemy_config.get_session() as db_session:
        tenant_service = TenantService(session=db_session)
        users = UserService(session=db_session)
        memberships = UserTenantMembershipService(session=db_session)

        # Pin the tenant UUID via repository.add: TenantService.create
        # would let advanced_alchemy assign a fresh UUIDv7. Tests need
        # the deterministic DEV_TENANT_ID for cross-fixture consistency.
        tenant = Tenant(id=DEV_TENANT_ID, display_name="Acme")
        await tenant_service.repository.add(tenant)
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
        user_id = user.id

    return DevAdmin(
        username=DEV_USERNAME,
        password=DEV_PASSWORD,
        user_id=user_id,
        tenant_id=DEV_TENANT_ID,
    )


@pytest.fixture
async def client(app: Litestar, dev_admin: DevAdmin) -> AsyncIterator[AsyncTestClient]:
    """An authenticated ``AsyncTestClient``.

    Logs in once on construction; ``httpx`` persists the session
    cookie across subsequent requests, so the rest of the test runs
    as the seeded admin. Tests exercising the rejection path use
    :func:`unauth_client` instead.
    """
    async with AsyncTestClient(app) as c:
        resp = await c.post(
            "/auth/login",
            json={
                "username": dev_admin.username,
                "password": dev_admin.password,
            },
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
