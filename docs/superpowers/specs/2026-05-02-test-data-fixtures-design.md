# Design: Test data fixtures

## Status

Approved 2026-05-02.

## Scope

Replace the ad-hoc per-test state-building helpers (`_make_active_truck`, `_make_parent`, `_make_field`, …) duplicated across `tests/schema/test_handlers_*.py` with a declarative fixture system derived from advanced-alchemy's `open_fixture_async` (see [database seeding docs](https://advanced-alchemy.litestar.dev/latest/usage/database_seeding.html)).

The system has two layers:

- **Atoms** — JSON files holding the rows for one logical "thing" (e.g., the row that defines a Truck asset type). Each atom is a row-list that advanced-alchemy can load directly.
- **Scenarios** — named tuples of atom paths in a single Python module. A scenario picks atoms, fixes their load order, and is the unit a test asks for.

The schema-side (`asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields`) ships the loader plus the three example scenarios shown below (`active_truck`, `deactivated_truck`, `active_truck_with_vin_field`) and the atoms they need. Data-side fixtures (`assets`, `event_log`, …) are not shipped — the directory shape accommodates them when the data-side services land.

## Goals

1. One JSON file per logical fixture row-set, version-controlled alongside tests.
2. Composing scenarios from atoms is a one-line Python edit; adding an atom is a single new file.
3. The loader infers the target service from the directory the JSON lives in (no per-step routing config).
4. The loader infers an "exports" map from the loaded rows so tests can reference seeded entities by name without hard-coding UUIDs at the call site.
5. Tests opt into a scenario through one pytest fixture: `seed(SCENARIO_NAME)` where the scenario constant is imported from `tests.data.scenarios`.
6. Loader is transactional and integrates with the existing `auto_commit=False` discipline used by domain handlers.
7. Batch insertion via `create_many` (per the docs' "Use batch operations" guidance), one flush per scenario.

## Non-goals

- **Data-side scenarios.** No `assets`/`event_log` fixtures in this round; the directory layout reserves space for them.
- **CSV.** JSON suffices for the column types in play (UUID strings, JsonB dicts, enum strings) and round-trips them without coercion. Advanced-alchemy supports `.json.gz`/`.csv` but we don't need them.
- **`upsert_many` re-runnable seeding.** Tests start from an empty in-memory SQLite per the existing `engine` fixture; idempotence isn't required.
- **Polyfactory integration.** Generated rather than declarative data is a separate concern; a future `seed_random()` could live alongside `seed()` without disturbing this design.
- **Migration of every existing `_make_*` helper.** Most of those helpers take parameters (`active=False`, etc.) that don't fit a snapshot-style atom and would force the scenario set to balloon. This PR migrates only the no-arg, fits-a-named-scenario callers in `tests/schema/test_handlers_asset_type.py` (the `_make_active_truck` / `_make_deactivated_truck` users) as proof-of-life. The other helpers stay as factory functions; bulk migration is opportunistic future work.
- **Templating across atoms.** FK references in atom JSON are hard-coded UUIDs. The atom file *name* signals which parent it expects (e.g., `vin_on_truck.json`).

## Architecture

### Module layout

```
tests/
├── conftest.py                            # add `seed` fixture
└── data/
    ├── __init__.py                        # package marker (no re-exports — tests import from .loader / .scenarios directly)
    ├── loader.py                          # NEW: load_scenario()
    ├── scenarios.py                       # NEW: scenario constants + Scenario type alias
    ├── fixtures/
    │   └── truck/                         # one dir per logical entity
    │       ├── asset_type.json            # the Truck asset_type row
    │       ├── asset_type__deactivated.json
    │       └── asset_type_field__vin.json # vin field on Truck
    └── test_loader.py                     # NEW: tests for the loader itself
```

### Atom files

A row-list of dicts decoded directly into the model. Tenant id, primary key id, and any FK columns are present and explicit.

Atoms are stored under `tests/data/fixtures/<entity>/<basename>.json`. The directory groups all fixtures for one logical entity (e.g., everything Truck-related under `truck/`); the basename is `<service_attr>[__<variant>]`, where the prefix names the target service on `ServiceBundle` and the optional variant disambiguates multiple fixtures targeting the same service from the same entity.

`tests/data/fixtures/truck/asset_type.json`:

```json
[
  {
    "tenant_id": "t1",
    "id": "00000000-0000-0000-0000-000000000001",
    "name": "Truck",
    "active": true
  }
]
```

`tests/data/fixtures/truck/asset_type_field__vin.json`:

```json
[
  {
    "tenant_id": "t1",
    "id": "00000000-0000-0000-0000-000000000010",
    "parent_id": "00000000-0000-0000-0000-000000000001",
    "name": "vin",
    "data_type": "text",
    "validation": null,
    "active": true
  }
]
```

Atoms are **snapshots, not parameterized templates.** A field for a different parent or with a different validation shape is a different atom file. The entity-rooted directory layout means everything related to one entity is in one place — `ls truck/` shows the full picture at a glance, instead of relationships being scattered across per-table directories.

### Scenarios

`tests/data/scenarios.py`:

```python
from typing import TypeAlias

Scenario: TypeAlias = tuple[str, ...]

ACTIVE_TRUCK: Scenario = ("truck/asset_type",)
DEACTIVATED_TRUCK: Scenario = ("truck/asset_type__deactivated",)
ACTIVE_TRUCK_WITH_VIN_FIELD: Scenario = (
    "truck/asset_type",
    "truck/asset_type_field__vin",
)
```

Each scenario is a tuple of `<entity>/<basename>` paths. Tuple order is **load order**: parents must precede children. UUIDs live only in the JSON atoms (canonical) and are returned by the loader's exports map — there are no Python-side UUID constants to keep in sync.

**Scenarios are module-level variables, not entries in a registry dict.** The cost is that there is no single `SCENARIOS.keys()` listing; the wins are (a) typos become `NameError` at import time instead of `KeyError` at runtime, (b) the loader's parameter is type-checked as `Scenario` at every call site, and (c) the loader needs no failure-mode test for "unknown name" — that mode no longer exists.

### Loader

`tests/data/loader.py`:

```python
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from advanced_alchemy.utils.fixtures import open_fixture_async
from sqlalchemy.ext.asyncio import AsyncSession

from novamoc.domain.schema._bundle import ServiceBundle

from tests.data.scenarios import Scenario

FIXTURES_PATH = Path(__file__).parent / "fixtures"


def _service_attr_for(basename: str) -> str:
    """The atom basename is ``<service_attr>[__<variant>]``; the prefix
    (before ``__``) is the target ServiceBundle attribute."""
    return basename.partition("__")[0]


async def load_scenario(
    scenario: Scenario,
    *,
    session: AsyncSession,
    services: ServiceBundle,
) -> Mapping[str, Mapping[str, UUID]]:
    """Load the given scenario.

    Reads each atom in scenario order via ``open_fixture_async`` and inserts
    via ``services.<inferred>.create_many(..., auto_commit=False)``. Builds
    an export map from the rows it loaded so tests can address seeded
    entities by name. Flushes once at the end; commit is left to the caller
    (the existing ``session`` fixture rolls back at teardown).

    Returns ``{service_attr: {row_name: UUID(row_id)}}``.
    """
    exports: dict[str, dict[str, UUID]] = {}

    for path in scenario:
        entity_dir, basename = path.split("/", 1)
        service_attr = _service_attr_for(basename)
        rows = await open_fixture_async(FIXTURES_PATH / entity_dir, basename)
        await getattr(services, service_attr).create_many(
            data=rows, auto_commit=False,
        )
        bucket = exports.setdefault(service_attr, {})
        for row in rows:
            bucket[row["name"]] = UUID(row["id"])

    await session.flush()
    return exports
```

Key behaviors:

- **Service inference.** `truck/asset_type_field__vin` → basename `asset_type_field__vin` → prefix before `__` is `asset_type_field` → `services.asset_type_field`. The basename's prefix names the target service directly; the directory groups fixtures by entity for human navigation. All current ServiceBundle attributes (`asset_type`, `asset_type_field`, `maintenance_record_type`, `maintenance_record_type_field`) work as filename prefixes without transformation.
- **Export inference.** Every schema entity has a unique-per-tenant `name` column, so `exports[service_attr][row["name"]]` is always well-defined for the entities we seed today. When data-side fixtures arrive, rows without a `name` will need a different keying rule (e.g., the row's `id` directly); decide that when the first data-side scenario is written.
- **Batch insertion.** One `create_many` call per atom file (the docs' explicit recommendation). One `session.flush()` for the whole scenario.
- **No commit.** Matches the rest of the test suite — the `session` fixture rolls back, the `app` fixture commits via `before_send_handler="autocommit"`. The loader stays neutral.
- **No `try/except`.** Missing JSON file raises `FileNotFoundError`. Unknown service attribute raises `AttributeError`. Loud failures are correct. (There is no "unknown scenario" error — typos at the call site are caught at import time as `NameError`.)

### Pytest integration

`tests/conftest.py` gains one fixture:

```python
from collections.abc import Mapping
from uuid import UUID

from tests.data.loader import load_scenario
from tests.data.scenarios import Scenario


@pytest.fixture
def seed(session, services):
    async def _seed(scenario: Scenario) -> Mapping[str, Mapping[str, UUID]]:
        return await load_scenario(scenario, session=session, services=services)
    return _seed
```

Test usage:

```python
from tests.data.scenarios import ACTIVE_TRUCK


async def test_update_truck_name(seed, services):
    ids = await seed(ACTIVE_TRUCK)
    truck_id = ids["asset_type"]["Truck"]
    # ... exercise the system under test against truck_id
```

The `seed` fixture is the single public entry point for *consumer* tests (i.e., handler tests, e2e tests). The loader's own self-tests in `tests/data/test_loader.py` import `load_scenario` directly — they have to, because they exercise the loader itself.

### Loader self-tests

`tests/data/test_loader.py` covers:

- A successful load: a scenario constant, all atoms inserted, exports map shape correct.
- Unknown atom path raises `FileNotFoundError` (passing a tuple with a non-existent path directly to `load_scenario`).
- The `_service_attr_for` rule: `asset_types` → `asset_type`, `asset_type_fields` → `asset_type_field`.
- Parent-before-child ordering is honored: load `ACTIVE_TRUCK_WITH_VIN_FIELD` and assert the field row exists with the expected `parent_id`.

## Best practices baked in

Drawn from advanced-alchemy's database seeding guide and adapted to a test (rather than production-seed) context:

| Guidance from docs                                       | How this design honors it                                                                |
|----------------------------------------------------------|------------------------------------------------------------------------------------------|
| Dedicated `fixtures/` directory                          | `tests/data/fixtures/` holds all atoms.                                                  |
| Batch operations (`add_many` / `upsert_many`) over per-row | Loader uses `services.<x>.create_many` exclusively.                                    |
| Seed parent tables before dependent child tables         | Each scenario's tuple order is load order; atoms with FKs must come after their parents. |
| Version control fixtures alongside application code      | Atoms live under `tests/`, change with the rest of the suite.                            |
| JSON over CSV when types matter                          | All atoms are JSON; UUID strings, JsonB dicts, enum strings round-trip natively.         |
| Migrations and seeding as separate steps                 | Test `engine` fixture creates schema (`create_all`); `seed()` is a separate call.        |
| Compression supported (`.json.gz`)                       | Not used — atoms are tiny. `open_fixture_async` will pick it up if a future atom needs it. |
| Polyfactory for generated data                           | Out of scope; can sit alongside this design later.                                       |

Project-specific additions:

- **No commit in the loader.** Composes with the existing handler pattern (`auto_commit=False`) and the `session` fixture's rollback at teardown.
- **One flush per scenario.** Cheaper than per-atom flushes; sufficient because nothing in a scenario observes intermediate state.
- **Deterministic UUIDs** in atoms so tests can assert on stable IDs and the exports map is reproducible across runs.

## Out-of-scope items the design accommodates without change

- **Adding more schema-side scenarios.** New atom file + new dict entry. No loader edit.
- **Data-side scenarios when those services exist.** `tests/data/fixtures/assets/`, `tests/data/fixtures/event_log/` plug into the same loader; only the export-keying rule needs revisiting (see Loader notes).
- **Future `seed_random()` for property-style tests.** Lives next to `seed()` in `conftest.py`; orthogonal to this system.
