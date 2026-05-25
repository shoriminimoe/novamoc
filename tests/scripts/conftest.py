"""Apply the ``no_tenant`` marker to every test in this directory.

The script-level tests under ``tests/scripts/`` exercise pure-Python
helpers under ``scripts/`` and never touch the database. They have no
need for the ambient tenant contextvar that the top-level ``tenant``
autouse fixture sets up, and they have no project tables to scope
against. Stamping the marker here keeps individual tests free of
fixture boilerplate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

# ``pytest_collection_modifyitems`` is called once per conftest with the
# *full* session item list, regardless of where the conftest lives. Filter
# to items whose file actually lives under this directory so we don't
# bleed ``no_tenant`` onto sibling test packages and disable their
# autouse tenant fixture.
_HERE = Path(__file__).parent


def _items_in_this_dir(items: Iterable[pytest.Item]) -> list[pytest.Item]:
    return [item for item in items if _HERE in item.path.parents]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in _items_in_this_dir(items):
        item.add_marker(pytest.mark.no_tenant)
