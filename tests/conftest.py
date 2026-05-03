"""Test fixtures.

Real in-memory SQLite per test session. No mocks — db-layer tests must hit
a real engine to catch migration-style drift early.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from uuid import UUID

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
from litestar.openapi.config import OpenAPIConfig
from litestar.plugins.problem_details import (
    ProblemDetailsConfig,
    ProblemDetailsPlugin,
)
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from novamoc.api._problem_details import (
    litestar_validation_error_to_problem_details,
    msgspec_validation_error_to_problem_details,
    schema_error_to_problem_details,
)
from novamoc.domain.schema._errors import SchemaError

# Importing the models registers their tables on the shared metadata registry.
import novamoc.db.models  # noqa: F401
from novamoc.domain.schema._bundle import ServiceBundle
from novamoc.domain.schema.controllers import SchemaController
from novamoc.domain.schema.services import (
    AssetTypeFieldService,
    AssetTypeService,
    MaintenanceRecordTypeFieldService,
    MaintenanceRecordTypeService,
    SchemaChangeLogService,
)

from tests.data.loader import load_scenario
from tests.data.scenarios import Scenario


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
) -> Callable[[Scenario], Awaitable[Mapping[str, Mapping[str, UUID]]]]:
    """Return an async ``seed(scenario)`` callable that loads a scenario.

    Wraps ``tests.data.loader.load_scenario`` with the per-test ``session``
    and ``services`` fixtures so test bodies stay focused on assertions:

        from tests.data.scenarios import ACTIVE_TRUCK

        async def test_x(seed, services):
            ids = await seed(ACTIVE_TRUCK)
            truck_id = ids["asset_type"]["Truck"]
    """

    async def _seed(scenario: Scenario) -> Mapping[str, Mapping[str, UUID]]:
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
            msgspec.ValidationError: msgspec_validation_error_to_problem_details,
            ValidationException: litestar_validation_error_to_problem_details,
        },
    )
    return Litestar(
        route_handlers=[SchemaController],
        plugins=[
            SQLAlchemyPlugin(config=alchemy_config),
            ProblemDetailsPlugin(config=problem_details_config),
        ],
        openapi_config=OpenAPIConfig(title="novaMOC", version="0.1.0", path="/openapi"),
    )


@pytest.fixture
async def client(app: Litestar):
    async with AsyncTestClient(app) as c:
        yield c
