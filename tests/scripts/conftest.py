"""Conftest for tests under ``tests/scripts/``.

Two responsibilities:

- Apply the ``no_tenant`` marker to every test in this directory. The
  script-level tests exercise pure-Python helpers under ``scripts/`` and
  never touch the database; they have no need for the ambient tenant
  contextvar the top-level ``tenant`` autouse fixture sets up, and no
  project tables to scope against.
- Scrub ``GITHUB_STEP_SUMMARY`` from the environment for every test.
  ``scripts/ratchet.py`` appends to the file pointed at by that env var,
  and several tests here call ``orchestrator.main()`` (which calls
  ``_write_step_summary``). When pytest itself is invoked from a CI job,
  the runner sets ``GITHUB_STEP_SUMMARY`` to the *job's* real summary
  file, and an un-monkeypatched test would leak ratchet output into the
  wrong job's summary. Tests that need the env var (e.g. the one that
  asserts the summary is written) set it explicitly via ``monkeypatch``.
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


@pytest.fixture(autouse=True)
def _scrub_github_step_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
