"""Apply the ``no_tenant`` marker to every test in this directory.

The script-level tests under ``tests/scripts/`` exercise pure-Python
helpers under ``scripts/`` and never touch the database. They have no
need for the ambient tenant contextvar that the top-level ``tenant``
autouse fixture sets up, and they have no project tables to scope
against. Stamping the marker here keeps individual tests free of
fixture boilerplate.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.no_tenant)
