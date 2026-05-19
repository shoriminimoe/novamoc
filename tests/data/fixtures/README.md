# Test data fixtures

You're writing a test that needs specific entity state pre-loaded into the in-memory database. This directory holds the JSON snapshots ("atoms") you compose into named scenarios in `tests/data/scenarios.py`, then load with `await seed(YOUR_SCENARIO)` from your test body.

## Layout at a glance

```
tests/data/fixtures/
└── <entity>/                              # one dir per logical entity
    ├── <service_attr>.json                # rows for that entity in <service_attr>'s table
    ├── <service_attr>__<variant>.json     # alternative state of the same
    └── <other_service_attr>__<role>.json  # related row in another table
```

Everything about Truck — the asset_type row, its deactivated variant, every field on it — lives under `truck/`. The directory groups by entity so you can `ls truck/` and see the full picture at a glance.

## Recipe

Worked example: you want a test where there's a Lorry asset type with a `mileage` number field on it.

### 1. Write the atom files

`tests/data/fixtures/lorry/asset_type.json`:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000020",
    "name": "Lorry",
    "active": true
  }
]
```

`tests/data/fixtures/lorry/asset_type_field__mileage.json`:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000021",
    "parent_id": "00000000-0000-0000-0000-000000000020",
    "name": "mileage",
    "data_type": "number",
    "validation": null,
    "active": true
  }
]
```

The directory `lorry/` says "this is about the Lorry entity." The filename prefix `asset_type_field` says "this row goes into the asset type fields table." The `__mileage` suffix distinguishes it from any other asset type field on Lorry.

### 2. Add a scenario

`tests/data/scenarios.py`:

```python
LORRY_WITH_MILEAGE_FIELD: Scenario = (
    "lorry/asset_type",
    "lorry/asset_type_field__mileage",
)
```

Tuple order is **load order** — parents before children that reference them.

### 3. Use it in the test

```python
from tests.data.scenarios import LORRY_WITH_MILEAGE_FIELD


async def test_lorry_mileage_constraint(seed, services):
    ids = await seed(LORRY_WITH_MILEAGE_FIELD)
    lorry_id = ids["asset_type"]["Lorry"]
    mileage_id = ids["asset_type_field"]["mileage"]
    # ... exercise the system under test against those ids
```

`seed` and `services` are pytest fixtures defined in `tests/conftest.py` — pytest injects them automatically when you list them as test parameters. `seed` wraps the loader with the per-test database session; `services` is the `ServiceBundle` of repositories you query/mutate against.

The exports map `seed` returns is keyed by `(service_attr, row["name"])` and yields each row's UUID. Use it instead of repeating literal UUIDs in your test body.

## Rules you have to follow

**Directory name = the entity.** Pick one name per logical thing (`truck`, `lorry`, `forklift`) and put every fixture related to it under that directory.

**Filename prefix = the target service attribute.** The loader splits the basename on `__` and looks up `services.<prefix>`. So `asset_type.json` targets `services.asset_type`; `asset_type_field__vin.json` targets `services.asset_type_field`. The variant suffix after `__` is for your eyes only — it disambiguates multiple fixtures targeting the same service from the same entity.

**One JSON file per logical row-set.** A Truck in the active state and a Truck in the deactivated state are two separate files (`truck/asset_type.json`, `truck/asset_type__deactivated.json`). No parameterisation, no templating — different state, different file.

**FK columns reference another atom's `id` literal.** No cross-atom templating; just paste the UUID. The directory grouping makes it obvious which atom you mean.

**All required model columns must be present.** A bare list of row dicts is passed straight to `<service>.create_many(...)`. Missing-required-column failures surface at insert time, not load time.

**UUIDs are deterministic.** Hard-code them. Pick clearly-distinct values; keep one entity's atoms numerically close (a Lorry parent at `...0020`, its fields at `...0021`, `...0022`, …). No central registry — pick a free range and let the JSON be the source of truth.

**Don't hard-code `tenant_id`.** The autouse `tenant` fixture in `tests/conftest.py` sets the storage-layer ContextVar to `tests._constants.DEV_TENANT_ID` for every test; Layer 2 of `db._listeners` auto-stamps `tenant_id` on every newly-flushed row. Multi-tenant tests parametrise the fixture across `DEV_TENANT_ID_A` / `DEV_TENANT_ID_B`.

## Breadcrumbs for the curious

- `tests/data/loader.py` — the loader. Thin: batch-insert via `create_many`, single flush, never commits.
- `tests/data/scenarios.py` — scenario constants and the `Scenario` type alias.
- `tests/conftest.py` — the `seed` pytest fixture (and the underlying `engine`, `session`, `services`).
- `tests/data/test_loader.py` — the loader's own self-tests.
- `docs/superpowers/specs/2026-05-02-test-data-fixtures-design.md` — design rationale (atoms-vs-scenarios, why module variables, the snapshots-not-templates trade-off).
