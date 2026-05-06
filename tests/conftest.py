"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec
import pytest
from advanced_alchemy.base import metadata_registry
from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from litestar import Litestar
from litestar.exceptions import ValidationException
from litestar.middleware.base import DefineMiddleware
from litestar.openapi.config import OpenAPIConfig
from litestar.plugins.problem_details import (
    ProblemDetailsConfig,
    ProblemDetailsPlugin,
)
from litestar.static_files import create_static_files_router
from litestar.testing import AsyncTestClient
from render_problem_docs import _default_src_dir, _default_titles, render_all
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Importing the listeners registers tenant-scoping event handlers on SQLAlchemy.
import novamoc.db._listeners

# Importing the models registers their tables on the shared metadata registry.
import novamoc.db.models  # noqa: F401
from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
    tenant_resolution_error_to_problem_details,
)
from novamoc.config import problem_html_dir
from novamoc.db._tenant_context import use_tenant
from novamoc.domain.accounts import (
    AuthenticationMiddleware,
    TenantContextMiddleware,
    TenantResolutionError,
)
from novamoc.domain.accounts._resolver import _TENANT_T1_DEV_TOKEN
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema._errors import SchemaError
from novamoc.domain.schema.controllers import SchemaController
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)
from tests.data.loader import load_scenario

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
    )

    from tests.data.scenarios import Scenario


@pytest.fixture(autouse=True)
def tenant(request: pytest.FixtureRequest) -> Iterator[str | None]:
    """Set the storage-layer tenant contextvar for every test's duration.

    Autouse so tests don't need to declare ``tenant`` purely to get a
    contextvar; defaults to "t1". Tests that need a specific tenant
    value (or want to flip across tenants) override via indirect
    parametrization, declaring ``tenant: str`` only when they actually
    read the value:

        @pytest.mark.parametrize("tenant", ["t-a", "t-b"], indirect=True)
        async def test_cross_tenant(tenant: str): ...

    Tests that must run with no tenant context (to assert the fail-closed
    paths in the listeners or to verify the contextvar primitive itself)
    opt out with the ``no_tenant`` marker:

        @pytest.mark.no_tenant
        async def test_unscoped_select_raises(): ...
    """
    if request.node.get_closest_marker("no_tenant"):
        yield None
        return
    tenant_id = getattr(request, "param", "t1")
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

        a_ids = await seed(ACTIVE_TRUCK, tenant_id="t-a")
        b_ids = await seed(ACTIVE_TRUCK, tenant_id="t-b")
    """

    async def _seed(
        scenario: Scenario,
        tenant_id: str | None = None,
    ) -> Mapping[str, Mapping[str, UUID]]:
        if tenant_id is not None:
            with use_tenant(tenant_id):
                return await load_scenario(scenario, session=session, services=services)
        return await load_scenario(scenario, session=session, services=services)

    return _seed


@pytest.fixture
async def app() -> Litestar:
    """A Litestar app with an in-memory SQLite for e2e tests.

    ``StaticPool`` forces the engine to keep one connection, so all
    queries (the plugin's request-scoped session, the autocommit
    handler, etc.) reach the same in-memory database. Each function-
    scoped fixture instance gets its own engine, so its database lives
    only for the duration of the test and dies when the engine is
    disposed at fixture teardown.
    """
    alchemy_config = SQLAlchemyAsyncConfig(
        connection_string="sqlite+aiosqlite:///:memory:",
        before_send_handler="autocommit",
        session_config=AsyncSessionConfig(expire_on_commit=False),
        create_all=True,
        engine_config=EngineConfig(poolclass=StaticPool),
    )
    problem_details_config = ProblemDetailsConfig(
        enable_for_all_http_exceptions=True,
        exception_to_problem_detail_map={  # ty: ignore[invalid-argument-type]
            SchemaError: schema_error_to_problem_details,
            TenantResolutionError: tenant_resolution_error_to_problem_details,
            msgspec.ValidationError: msgspec_validation_error_to_problem_details,
            ValidationException: litestar_validation_error_to_problem_details,
        },
    )
    problem_docs_router = create_static_files_router(
        path="/problems",
        directories=[str(problem_html_dir())],
        name="problems",
    )
    return Litestar(
        route_handlers=[SchemaController, problem_docs_router],
        middleware=[
            DefineMiddleware(
                AuthenticationMiddleware,
                exclude=r"^/(openapi|problems)",
            ),
            TenantContextMiddleware(),
        ],
        plugins=[
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )


@pytest.fixture
async def client(app: Litestar):
    async with AsyncTestClient(app) as c:
        # AsyncTestClient does not accept ``headers`` at construction; we set
        # them on the underlying httpx client so every request carries the dev
        # bearer by default. Tests that exercise the rejection path override
        # the header per-request.
        c.headers["Authorization"] = f"Bearer {_TENANT_T1_DEV_TOKEN}"
        yield c


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """Session-scoped sibling of pytest's built-in ``monkeypatch`` (which
    is function-scoped). Used by other session-scoped fixtures that need
    to set env vars for the entire test run."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def _problem_docs_base_url(
    monkeypatch_session: pytest.MonkeyPatch,
) -> None:
    """Pin NOVAMOC_PROBLEM_DOCS_BASE_URL for every test in the session.

    Tests assert against type URIs of the form ``http://test/problems/<code>.html``
    rather than whatever the developer's shell happens to export.
    """

    monkeypatch_session.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://test")


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
