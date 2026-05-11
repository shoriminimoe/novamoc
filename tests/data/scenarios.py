"""Named compositions of fixture atoms.

Each scenario is a tuple of ``<entity>/<basename>`` paths under
``tests/data/fixtures/``. Basename is ``<service_attr>[__<variant>]`` —
see ``loader.py`` for the convention. Tuple order is load order:
parents before children. Tests import the scenarios they want and pass
them to ``seed(...)`` or ``load_scenario(...)``.
"""

from __future__ import annotations

type Scenario = tuple[str, ...]

ACTIVE_TRUCK: Scenario = ("truck/asset_type",)
DEACTIVATED_TRUCK: Scenario = ("truck/asset_type__deactivated",)
ACTIVE_TRUCK_WITH_VIN_FIELD: Scenario = (
    "truck/asset_type",
    "truck/asset_type_field__vin",
)
ACTIVE_OIL_CHANGE_WITH_NOTES: Scenario = (
    "oil_change/maintenance_record_type",
    "oil_change/maintenance_record_type_field__notes",
)
