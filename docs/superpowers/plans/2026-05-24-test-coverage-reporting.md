# Test Coverage Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire coverage into both test suites, refactor the ratchet into a multi-checker orchestrator that gates coverage regressions, and stand up the project's first GitHub Actions workflow surfacing the result in CI.

**Architecture:** Coverage runs opt-in via `just coverage` (preserving the fast `just test` loop). `scripts/ratchet.py` becomes a thin orchestrator over independent checkers in `scripts/ratchets/`; the existing ruff logic moves verbatim, a new coverage checker reads `coverage.xml` + `coverage-summary.json` from disk. CI runs `lint → typecheck → coverage → ratchet` in one sequential job and uploads HTML reports as artifacts; the orchestrator writes a markdown summary to `$GITHUB_STEP_SUMMARY` when the env var is set.

**Tech Stack:** Python 3.14 + `pytest-cov` + `coverage.py`; Vitest + `@vitest/coverage-v8`; GitHub Actions (ubuntu-latest); existing tooling (`uv`, `ruff`, `ty`, `just`).

**Reference spec:** `docs/superpowers/specs/2026-05-24-test-coverage-reporting-design.md`

---

## File structure

**Create:**

| Path | Purpose |
|---|---|
| `scripts/ratchets/__init__.py` | Package marker |
| `scripts/ratchets/_types.py` | `RatchetResult` + `MetricChange` dataclasses, summary-line renderers |
| `scripts/ratchets/ruff.py` | Ruff checker, extracted from current `scripts/ratchet.py` |
| `scripts/ratchets/coverage.py` | Coverage checker — reads `coverage.xml` + `src/js/web/coverage/coverage-summary.json`, compares to `.coverage-ratchet.json` |
| `.coverage-ratchet.json` | 4-number baseline |
| `.github/workflows/ci.yml` | First CI workflow |
| `tests/scripts/__init__.py` | Package marker |
| `tests/scripts/conftest.py` | Marks all tests in dir with `no_tenant` so the autouse tenant fixture is bypassed |
| `tests/scripts/test_coverage_ratchet.py` | Unit tests for `scripts/ratchets/coverage.py` |
| `tests/scripts/test_orchestrator.py` | Unit tests for orchestrator exit-code aggregation + step-summary writer |
| `tests/scripts/data/coverage_clean.xml` | Fixture: well-formed `coverage.xml` |
| `tests/scripts/data/coverage_summary_clean.json` | Fixture: well-formed vitest `coverage-summary.json` |

**Modify:**

| Path | Change |
|---|---|
| `scripts/ratchet.py` | Become orchestrator (calls every checker, aggregates exit code, writes step-summary) |
| `pyproject.toml` | Add `pytest-cov>=6.0.0` dev-dep; add `[tool.coverage.*]` blocks |
| `src/js/web/package.json` | Add `@vitest/coverage-v8` dev-dep |
| `src/js/web/vite.config.ts` | Add `test.coverage` block |
| `justfile` | Add `coverage`, `coverage-py`, `coverage-js` recipes; swap `test` → `coverage` in `check` |
| `.gitignore` | Add `coverage.xml`, `.coverage.*`, `src/js/web/coverage/` |

---

## Task 1: Add coverage artifacts to `.gitignore`

Prevents accidental commits of measurement output before the tooling is wired up.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add the three patterns**

After the existing `.pytest_cache/` / `.coverage` / `htmlcov/` / `.ruff_cache/` block (line ~34), add:

```
coverage.xml
.coverage.*
src/js/web/coverage/
```

`coverage.xml` (Cobertura XML) lives at repo root; `.coverage.*` covers parallel-mode data files in case `coverage run -p` is added later; the vitest output dir is per-app.

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore(ignore): exclude coverage artifacts"
```

---

## Task 2: Configure `pytest-cov` and `coverage.py` in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `pytest-cov` to the `dev` dependency group**

In `[dependency-groups]`, append to the `dev` list:

```toml
dev = [
    "hypothesis>=6.0.0",
    "markdown-it-py>=3.0.0",
    "pytest>=9.0.3",
    "pytest-asyncio>=1.3.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.15.12",
    "ty>=0.0.34",
]
```

- [ ] **Step 2: Add `[tool.coverage.*]` blocks**

After `[tool.pytest.ini_options]` (around line 184), append:

```toml
[tool.coverage.run]
# Import name (resolved via the editable install). Tests and scripts/ live
# outside this package and are excluded by virtue of not being included.
source = ["novamoc"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
# Ratchet enforces the floor; don't have coverage.py duplicate-fail.
fail_under = 0
exclude_also = [
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]

[tool.coverage.xml]
output = "coverage.xml"

[tool.coverage.html]
directory = "htmlcov"
```

- [ ] **Step 3: Install the new dep**

Run: `uv sync`
Expected: `pytest-cov` resolves and installs without conflict; `uv.lock` updates.

- [ ] **Step 4: Smoke-test the new tooling**

Run: `uv run pytest --cov --cov-branch --cov-report=term -q`
Expected: tests pass; final lines print a per-file coverage table and a `TOTAL` row with line + branch percentages. A `coverage.xml` file appears at repo root (deleted after — task 1's gitignore covers it).

Delete the smoke artifact: `rm coverage.xml`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(coverage): wire pytest-cov + coverage.py config"
```

---

## Task 3: Configure `@vitest/coverage-v8` in the frontend

**Files:**
- Modify: `src/js/web/package.json`
- Modify: `src/js/web/vite.config.ts`

- [ ] **Step 1: Add `@vitest/coverage-v8` to devDependencies**

Run from `src/js/web/`:

```bash
cd src/js/web && npm install --save-dev @vitest/coverage-v8@^4.1.6
```

Expected: `package.json` gains the entry; `package-lock.json` updates.

- [ ] **Step 2: Add the `coverage` block to `vite.config.ts`**

In `src/js/web/vite.config.ts`, replace the `test: { ... }` block with:

```ts
test: {
  // Component tests run in jsdom; Playwright e2e is a separate suite under tests/e2e/.
  environment: 'jsdom',
  globals: true,
  include: ['tests/component/**/*.test.ts'],
  setupFiles: ['./tests/component/setup.ts'],
  coverage: {
    provider: 'v8',
    reporter: ['text', 'html', 'json-summary'],
    reportsDirectory: 'coverage',
    include: ['src/**/*.{ts,svelte}'],
    exclude: ['src/**/*.d.ts', 'tests/**', 'tests/e2e/**'],
    // No `thresholds:` block — the ratchet does the gating. Setting a
    // threshold here would either duplicate the ratchet's role or fight it.
    all: true,
  },
},
```

- [ ] **Step 3: Smoke-test the new tooling**

Run from `src/js/web/`:

```bash
cd src/js/web && npm run test -- --coverage
```

Expected: tests pass; a terminal coverage table prints; `src/js/web/coverage/coverage-summary.json` and `src/js/web/coverage/index.html` exist.

Delete the smoke artifact: `rm -rf src/js/web/coverage/`.

- [ ] **Step 4: Commit**

```bash
git add src/js/web/package.json src/js/web/package-lock.json src/js/web/vite.config.ts
git commit -m "feat(coverage): wire @vitest/coverage-v8"
```

---

## Task 4: Add `coverage` recipes to the justfile

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Add the recipes**

After the `test-js-e2e` recipe (around line 64), append:

```just
# Run both test suites under coverage and write artifacts
[parallel]
coverage: coverage-py coverage-js

# Python coverage: writes coverage.xml + htmlcov/
coverage-py:
	uv run pytest --cov --cov-branch --cov-report=xml --cov-report=html --cov-report=term

# JS coverage: writes src/js/web/coverage/
coverage-js:
	cd src/js/web && npm run test -- --coverage
```

- [ ] **Step 2: Smoke-test the new recipes**

Run: `just coverage`
Expected: both recipes run; `coverage.xml`, `htmlcov/`, and `src/js/web/coverage/coverage-summary.json` all exist at the end.

Delete the smoke artifacts: `rm -rf coverage.xml htmlcov src/js/web/coverage/`.

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "feat(just): coverage / coverage-py / coverage-js recipes"
```

---

## Task 5: Scaffold the `scripts/ratchets/` package + `RatchetResult`

This task creates the shared dataclasses that both checkers will produce. It does NOT yet refactor `scripts/ratchet.py` — that's Task 7.

**Files:**
- Create: `scripts/ratchets/__init__.py`
- Create: `scripts/ratchets/_types.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/conftest.py`
- Create: `tests/scripts/test_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/__init__.py` (empty file).

Create `tests/scripts/conftest.py`:

```python
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.no_tenant)
```

Create `tests/scripts/test_types.py`:

```python
"""Tests for ``scripts/ratchets/_types``."""

from __future__ import annotations

from ratchets._types import MetricChange, RatchetResult


def test_clean_result_has_no_failure() -> None:
    result = RatchetResult(name="ruff", regressions=(), improvements=())
    assert result.has_failure is False
    assert result.setup_error is None


def test_regression_is_a_failure() -> None:
    result = RatchetResult(
        name="ruff",
        regressions=(MetricChange("PLR0913", old=4, new=5),),
        improvements=(),
    )
    assert result.has_failure is True


def test_improvement_is_a_failure() -> None:
    # Improvements demand an explicit baseline bump — they fail the gate just
    # like regressions, so users notice and run `just ratchet-update`.
    result = RatchetResult(
        name="ruff",
        regressions=(),
        improvements=(MetricChange("PLR0913", old=5, new=4),),
    )
    assert result.has_failure is True


def test_setup_error_alone_is_not_a_failure() -> None:
    result = RatchetResult(
        name="coverage",
        regressions=(),
        improvements=(),
        setup_error="coverage.xml not found",
    )
    assert result.has_failure is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_types.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'ratchets'`.

- [ ] **Step 3: Create the package + dataclass module**

Create `scripts/ratchets/__init__.py` (empty file).

Create `scripts/ratchets/_types.py`:

```python
"""Shared dataclasses produced by every ratchet checker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricChange:
    """A single metric's old and new values.

    The ``metric`` label is checker-specific:
    - Ruff: rule code, e.g. ``"PLR0913"``. Values are ``int`` counts.
    - Coverage: dotted metric path, e.g. ``"python.line"``. Values are
      ``float`` percentages.
    """

    metric: str
    old: float
    new: float


@dataclass(frozen=True, slots=True)
class RatchetResult:
    """Outcome of one independent ratchet checker.

    ``regressions`` and ``improvements`` are mutually-disjoint slices of
    the same diff. ``setup_error``, when set, means the checker could not
    run (e.g. missing input artifact); other checkers in the orchestrator
    still run.
    """

    name: str
    regressions: tuple[MetricChange, ...]
    improvements: tuple[MetricChange, ...]
    setup_error: str | None = None

    @property
    def has_failure(self) -> bool:
        return bool(self.regressions or self.improvements)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_types.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/ratchets/__init__.py scripts/ratchets/_types.py tests/scripts/__init__.py tests/scripts/conftest.py tests/scripts/test_types.py
git commit -m "feat(ratchet): RatchetResult + MetricChange dataclasses"
```

---

## Task 6: Extract the ruff checker into `scripts/ratchets/ruff.py`

Pure refactor: existing `current_counts` / `load_baseline` / `write_baseline` / `diff` logic moves into a single `check(*, update: bool) -> RatchetResult` function. The current `scripts/ratchet.py` is updated to call the new module (still single-checker; Task 7 makes it multi-checker).

**Files:**
- Create: `scripts/ratchets/ruff.py`
- Modify: `scripts/ratchet.py` (interim form — still ruff-only)

- [ ] **Step 1: Write `scripts/ratchets/ruff.py`**

```python
"""Ruff violation ratchet checker.

Counts per-rule violations from a fresh ``ruff check`` and compares them to
the committed ``.ruff-ratchet.json`` baseline. Returns a ``RatchetResult``;
callers (the orchestrator) handle aggregation, printing, and exit code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ratchets._types import MetricChange, RatchetResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = REPO_ROOT / ".ruff-ratchet.json"


def _current_counts() -> dict[str, int]:
    """Return ``{rule_code: count}`` from a fresh ``ruff check`` run."""
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "--no-fix", "--output-format=json", "."],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write("ratchet: failed to parse ruff output\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        sys.exit(2)
    return dict(Counter(v["code"] for v in violations))


def _load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text())


def _write_baseline(counts: dict[str, int]) -> None:
    payload = json.dumps(counts, indent=2, sort_keys=True) + "\n"
    BASELINE.write_text(payload)


def _diff(
    baseline: dict[str, int], current: dict[str, int]
) -> tuple[tuple[MetricChange, ...], tuple[MetricChange, ...]]:
    rules = sorted(set(baseline) | set(current))
    regressions: list[MetricChange] = []
    improvements: list[MetricChange] = []
    for rule in rules:
        old = baseline.get(rule, 0)
        new = current.get(rule, 0)
        if new > old:
            regressions.append(MetricChange(rule, old=old, new=new))
        elif new < old:
            improvements.append(MetricChange(rule, old=old, new=new))
    return tuple(regressions), tuple(improvements)


def check(*, update: bool = False) -> RatchetResult:
    """Run the ruff ratchet check.

    Args:
        update: When ``True``, rewrite the baseline from current counts.

    Returns:
        A ``RatchetResult``. When ``update`` is ``True``, the result has
        no regressions or improvements (the baseline now matches current
        state). When the baseline file does not exist and ``update`` is
        ``False``, returns a setup-error result asking the user to run
        ``just ratchet-update`` first.
    """
    current = _current_counts()

    if update:
        _write_baseline(current)
        return RatchetResult(name="ruff", regressions=(), improvements=())

    if not BASELINE.exists():
        return RatchetResult(
            name="ruff",
            regressions=(),
            improvements=(),
            setup_error=(
                f"No baseline at {BASELINE.relative_to(REPO_ROOT)}. "
                "Run `just ratchet-update` to create one."
            ),
        )

    baseline = _load_baseline()
    regressions, improvements = _diff(baseline, current)
    return RatchetResult(
        name="ruff",
        regressions=regressions,
        improvements=improvements,
    )
```

- [ ] **Step 2: Rewrite `scripts/ratchet.py` to call the new module (still single-checker)**

Replace the entire contents of `scripts/ratchet.py`:

```python
"""Ratchet orchestrator.

Runs every independent ratchet checker, accumulates results, prints them,
and exits with an aggregate code:

- ``0`` — every checker clean.
- ``1`` — at least one checker has regressions or improvements.
- ``2`` — at least one checker hit a setup error and no checker has a
  regression/improvement. Hard failures (exit ``1``) take precedence.

Usage:
    python scripts/ratchet.py            # check all ratchets
    python scripts/ratchet.py --update   # rewrite every baseline that can be
"""

from __future__ import annotations

import argparse
import sys

from ratchets import ruff
from ratchets._types import RatchetResult


def _render(result: RatchetResult) -> str:
    """Format a single checker's result for stdout (and step-summary fallback)."""
    lines = [f"=== {result.name} ratchet ==="]
    if result.setup_error:
        lines.append(f"Setup error: {result.setup_error}")
    elif result.regressions:
        lines.append("Ratchet regressions:")
        for change in result.regressions:
            delta = change.new - change.old
            lines.append(f"  {change.metric}: {change.old} -> {change.new} (+{delta})")
    elif result.improvements:
        lines.append("Ratchet improvements:")
        for change in result.improvements:
            delta = change.old - change.new
            lines.append(f"  {change.metric}: {change.old} -> {change.new} (-{delta})")
        lines.append("Run `just ratchet-update` to commit the lower baseline.")
    else:
        lines.append("Ratchet OK: baseline matches.")
    return "\n".join(lines)


def _exit_code(results: list[RatchetResult]) -> int:
    if any(r.has_failure for r in results):
        return 1
    if any(r.setup_error for r in results):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every independent ratchet check.")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite every baseline that can be updated from current state.",
    )
    args = parser.parse_args()

    results = [ruff.check(update=args.update)]

    for result in results:
        print(_render(result))
        print()

    if args.update:
        failed = [r.name for r in results if r.setup_error]
        if failed:
            print(f"Could not update: {', '.join(failed)}.")
            return 2
        print("Baselines updated.")
        return 0

    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify the refactor preserves behaviour**

Run: `just ratchet`
Expected: same output structure as before (now prefixed by `=== ruff ratchet ===`), same exit code on current `main`'s state.

Run: `uv run python scripts/ratchet.py --help`
Expected: argparse help text, no crash.

- [ ] **Step 4: Commit**

```bash
git add scripts/ratchet.py scripts/ratchets/ruff.py
git commit -m "refactor(ratchet): extract ruff checker behind RatchetResult API"
```

---

## Task 7: Write the coverage checker (TDD)

The coverage checker is the new logic. We test the parser + diff in isolation, using on-disk fixtures.

**Files:**
- Create: `tests/scripts/data/coverage_clean.xml`
- Create: `tests/scripts/data/coverage_summary_clean.json`
- Create: `tests/scripts/test_coverage_ratchet.py`
- Create: `scripts/ratchets/coverage.py`

- [ ] **Step 1: Create the fixture files**

Create `tests/scripts/data/coverage_clean.xml` (minimal Cobertura — only the attributes the parser reads):

```xml
<?xml version="1.0" ?>
<coverage line-rate="0.8845" branch-rate="0.7612" version="7.0" timestamp="0">
  <packages>
    <package name="novamoc" line-rate="0.8845" branch-rate="0.7612">
      <classes/>
    </package>
  </packages>
</coverage>
```

Create `tests/scripts/data/coverage_summary_clean.json` (minimal vitest json-summary — only the totals the parser reads):

```json
{
  "total": {
    "lines":     { "total": 100, "covered": 65, "skipped": 0, "pct": 65.30 },
    "statements":{ "total": 100, "covered": 65, "skipped": 0, "pct": 65.30 },
    "functions": { "total": 100, "covered": 65, "skipped": 0, "pct": 65.30 },
    "branches":  { "total": 100, "covered": 58, "skipped": 0, "pct": 58.10 }
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/scripts/test_coverage_ratchet.py`:

```python
"""Tests for ``scripts/ratchets/coverage``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratchets import coverage as cov_ratchet

FIXTURES = Path(__file__).parent / "data"
CLEAN_XML = FIXTURES / "coverage_clean.xml"
CLEAN_JSON = FIXTURES / "coverage_summary_clean.json"


def _baseline(tmp_path: Path, *, py_line: float, py_branch: float, js_line: float, js_branch: float) -> Path:
    path = tmp_path / ".coverage-ratchet.json"
    path.write_text(
        json.dumps({
            "python": {"line": py_line, "branch": py_branch},
            "js":     {"line": js_line, "branch": js_branch},
        }, indent=2) + "\n"
    )
    return path


def test_parse_python_coverage_xml() -> None:
    line, branch = cov_ratchet._parse_python_coverage(CLEAN_XML)
    assert line == pytest.approx(88.45)
    assert branch == pytest.approx(76.12)


def test_parse_js_coverage_summary() -> None:
    line, branch = cov_ratchet._parse_js_coverage(CLEAN_JSON)
    assert line == pytest.approx(65.30)
    assert branch == pytest.approx(58.10)


def test_check_clean_returns_no_changes(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path, py_line=88.45, py_branch=76.12, js_line=65.30, js_branch=58.10)
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=CLEAN_XML,
        coverage_summary=CLEAN_JSON,
    )
    assert result.name == "coverage"
    assert result.regressions == ()
    assert result.improvements == ()
    assert result.setup_error is None


def test_check_regression_when_python_line_drops(tmp_path: Path) -> None:
    # Baseline higher than fixture's 88.45 -> python.line is a regression.
    baseline = _baseline(tmp_path, py_line=90.00, py_branch=76.12, js_line=65.30, js_branch=58.10)
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=CLEAN_XML,
        coverage_summary=CLEAN_JSON,
    )
    metrics = {c.metric for c in result.regressions}
    assert metrics == {"python.line"}
    [change] = result.regressions
    assert change.old == pytest.approx(90.00)
    assert change.new == pytest.approx(88.45)


def test_check_improvement_when_js_branch_rises(tmp_path: Path) -> None:
    # Baseline lower than fixture's 58.10 -> js.branch is an improvement.
    baseline = _baseline(tmp_path, py_line=88.45, py_branch=76.12, js_line=65.30, js_branch=55.00)
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=CLEAN_XML,
        coverage_summary=CLEAN_JSON,
    )
    metrics = {c.metric for c in result.improvements}
    assert metrics == {"js.branch"}


def test_check_missing_xml_returns_setup_error(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path, py_line=0, py_branch=0, js_line=0, js_branch=0)
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=tmp_path / "missing.xml",
        coverage_summary=CLEAN_JSON,
    )
    assert result.setup_error is not None
    assert "coverage.xml" in result.setup_error


def test_check_missing_summary_returns_setup_error(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path, py_line=0, py_branch=0, js_line=0, js_branch=0)
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=CLEAN_XML,
        coverage_summary=tmp_path / "missing.json",
    )
    assert result.setup_error is not None
    assert "coverage-summary.json" in result.setup_error


def test_check_missing_baseline_returns_setup_error(tmp_path: Path) -> None:
    result = cov_ratchet.check(
        baseline_path=tmp_path / "missing-baseline.json",
        coverage_xml=CLEAN_XML,
        coverage_summary=CLEAN_JSON,
    )
    assert result.setup_error is not None
    assert ".coverage-ratchet.json" in result.setup_error


def test_update_writes_current_values(tmp_path: Path) -> None:
    baseline = tmp_path / ".coverage-ratchet.json"
    # No baseline yet — update mode is allowed to create it.
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=CLEAN_XML,
        coverage_summary=CLEAN_JSON,
        update=True,
    )
    assert result.setup_error is None
    written = json.loads(baseline.read_text())
    assert written == {
        "python": {"line": pytest.approx(88.45), "branch": pytest.approx(76.12)},
        "js":     {"line": pytest.approx(65.30), "branch": pytest.approx(58.10)},
    }


def test_update_refuses_when_artifacts_missing(tmp_path: Path) -> None:
    baseline = tmp_path / ".coverage-ratchet.json"
    result = cov_ratchet.check(
        baseline_path=baseline,
        coverage_xml=tmp_path / "missing.xml",
        coverage_summary=CLEAN_JSON,
        update=True,
    )
    assert result.setup_error is not None
    assert not baseline.exists()  # update must not silently zero the baseline
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_coverage_ratchet.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'ratchets.coverage'`.

- [ ] **Step 4: Implement `scripts/ratchets/coverage.py`**

```python
"""Coverage ratchet checker.

Reads ``coverage.xml`` (Cobertura, from pytest-cov) and the vitest
``coverage-summary.json`` from disk, compares the four overall percentages
against ``.coverage-ratchet.json``, and returns a ``RatchetResult``.

The checker does **not** run the test suite — producing the artifacts is
``just coverage``'s job. When an artifact or the baseline is missing, the
checker returns a ``RatchetResult`` whose ``setup_error`` tells the user
what to do; the orchestrator's other checkers still run.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ratchets._types import MetricChange, RatchetResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_BASELINE = REPO_ROOT / ".coverage-ratchet.json"
DEFAULT_PY_XML = REPO_ROOT / "coverage.xml"
DEFAULT_JS_SUMMARY = REPO_ROOT / "src" / "js" / "web" / "coverage" / "coverage-summary.json"


def _parse_python_coverage(path: Path) -> tuple[float, float]:
    """Return ``(line_pct, branch_pct)`` from a Cobertura ``coverage.xml``.

    coverage.py emits ``line-rate``/``branch-rate`` as fractions in ``[0, 1]``;
    we expose percentages in ``[0, 100]``.
    """
    tree = ET.parse(path)  # noqa: S314  -- our own coverage.xml, not user input
    root = tree.getroot()
    line = float(root.attrib["line-rate"]) * 100
    branch = float(root.attrib["branch-rate"]) * 100
    return round(line, 2), round(branch, 2)


def _parse_js_coverage(path: Path) -> tuple[float, float]:
    """Return ``(line_pct, branch_pct)`` from vitest's ``coverage-summary.json``."""
    data = json.loads(path.read_text())
    total = data["total"]
    return round(float(total["lines"]["pct"]), 2), round(float(total["branches"]["pct"]), 2)


def _load_baseline(path: Path) -> dict[str, dict[str, float]]:
    return json.loads(path.read_text())


def _write_baseline(path: Path, py: tuple[float, float], js: tuple[float, float]) -> None:
    payload = {
        "python": {"line": py[0], "branch": py[1]},
        "js":     {"line": js[0], "branch": js[1]},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _diff(
    baseline: dict[str, dict[str, float]], current: dict[str, dict[str, float]]
) -> tuple[tuple[MetricChange, ...], tuple[MetricChange, ...]]:
    regressions: list[MetricChange] = []
    improvements: list[MetricChange] = []
    for suite in ("python", "js"):
        for metric in ("line", "branch"):
            label = f"{suite}.{metric}"
            old = baseline[suite][metric]
            new = current[suite][metric]
            if new < old:
                regressions.append(MetricChange(label, old=old, new=new))
            elif new > old:
                improvements.append(MetricChange(label, old=old, new=new))
    return tuple(regressions), tuple(improvements)


def check(
    *,
    baseline_path: Path = DEFAULT_BASELINE,
    coverage_xml: Path = DEFAULT_PY_XML,
    coverage_summary: Path = DEFAULT_JS_SUMMARY,
    update: bool = False,
) -> RatchetResult:
    """Run the coverage ratchet check.

    Args:
        baseline_path: ``.coverage-ratchet.json`` location.
        coverage_xml: pytest-cov Cobertura output.
        coverage_summary: vitest json-summary output.
        update: When ``True``, rewrite the baseline from current values.

    Returns:
        A ``RatchetResult``. ``setup_error`` is set when any required input
        is missing; in update mode the baseline is left untouched in that
        case.
    """
    if not coverage_xml.exists():
        return RatchetResult(
            name="coverage",
            regressions=(),
            improvements=(),
            setup_error=f"{coverage_xml.name} not found. Run `just coverage` first.",
        )
    if not coverage_summary.exists():
        return RatchetResult(
            name="coverage",
            regressions=(),
            improvements=(),
            setup_error=f"{coverage_summary.name} not found. Run `just coverage` first.",
        )

    py = _parse_python_coverage(coverage_xml)
    js = _parse_js_coverage(coverage_summary)

    if update:
        _write_baseline(baseline_path, py, js)
        return RatchetResult(name="coverage", regressions=(), improvements=())

    if not baseline_path.exists():
        return RatchetResult(
            name="coverage",
            regressions=(),
            improvements=(),
            setup_error=(
                f"No baseline at {baseline_path.name}. "
                "Run `just ratchet-update` to create one."
            ),
        )

    baseline = _load_baseline(baseline_path)
    current = {"python": {"line": py[0], "branch": py[1]},
               "js":     {"line": js[0], "branch": js[1]}}
    regressions, improvements = _diff(baseline, current)
    return RatchetResult(
        name="coverage",
        regressions=regressions,
        improvements=improvements,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_coverage_ratchet.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/ratchets/coverage.py tests/scripts/test_coverage_ratchet.py tests/scripts/data/coverage_clean.xml tests/scripts/data/coverage_summary_clean.json
git commit -m "feat(ratchet): coverage checker"
```

---

## Task 8: Wire the coverage checker into the orchestrator

**Files:**
- Modify: `scripts/ratchet.py`
- Create: `tests/scripts/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_orchestrator.py`:

```python
"""Tests for the ratchet orchestrator's aggregation logic."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the script as a module — ``scripts/`` is on pythonpath.
import ratchet as orchestrator  # noqa: E402

from ratchets._types import MetricChange, RatchetResult


def _clean(name: str) -> RatchetResult:
    return RatchetResult(name=name, regressions=(), improvements=())


def _regressed(name: str) -> RatchetResult:
    return RatchetResult(
        name=name,
        regressions=(MetricChange("x", old=10, new=12),),
        improvements=(),
    )


def _improved(name: str) -> RatchetResult:
    return RatchetResult(
        name=name,
        regressions=(),
        improvements=(MetricChange("x", old=12, new=10),),
    )


def _setup_error(name: str) -> RatchetResult:
    return RatchetResult(name=name, regressions=(), improvements=(), setup_error="missing")


def test_exit_code_clean() -> None:
    assert orchestrator._exit_code([_clean("a"), _clean("b")]) == 0


def test_exit_code_regression_returns_1() -> None:
    assert orchestrator._exit_code([_clean("a"), _regressed("b")]) == 1


def test_exit_code_improvement_returns_1() -> None:
    assert orchestrator._exit_code([_clean("a"), _improved("b")]) == 1


def test_exit_code_setup_error_alone_returns_2() -> None:
    assert orchestrator._exit_code([_clean("a"), _setup_error("b")]) == 2


def test_exit_code_regression_beats_setup_error() -> None:
    # Hard failure precedence: 1 wins over 2.
    assert orchestrator._exit_code([_regressed("a"), _setup_error("b")]) == 1


def test_main_runs_every_checker_even_when_one_fails(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(orchestrator.ruff, "check", return_value=_regressed("ruff")), \
         patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")), \
         patch.object(sys, "argv", ["ratchet.py"]):
        rc = orchestrator.main()
    captured = capsys.readouterr().out
    assert "=== ruff ratchet ===" in captured
    assert "=== coverage ratchet ===" in captured
    assert rc == 1


def test_step_summary_written_when_env_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    with patch.object(orchestrator.ruff, "check", return_value=_regressed("ruff")), \
         patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")), \
         patch.object(sys, "argv", ["ratchet.py"]):
        orchestrator.main()
    md = summary_path.read_text()
    assert "ruff" in md
    assert "coverage" in md
    # Regressed checker should be flagged in the summary.
    assert "FAIL" in md or "regress" in md.lower()


def test_step_summary_skipped_without_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with patch.object(orchestrator.ruff, "check", return_value=_clean("ruff")), \
         patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")), \
         patch.object(sys, "argv", ["ratchet.py"]):
        rc = orchestrator.main()
    # No env, no file — nothing to assert beyond "didn't crash".
    assert rc == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_orchestrator.py -v`
Expected: 8 failures — `AttributeError: module 'ratchet' has no attribute 'coverage'` (or similar) on most tests; the step-summary tests fail because the writer doesn't exist yet.

- [ ] **Step 3: Update `scripts/ratchet.py` to call both checkers and write step-summary**

Replace the contents of `scripts/ratchet.py`:

```python
"""Ratchet orchestrator.

Runs every independent ratchet checker, accumulates results, prints them,
appends a markdown summary to ``$GITHUB_STEP_SUMMARY`` when set, and exits
with an aggregate code:

- ``0`` — every checker clean.
- ``1`` — at least one checker has regressions or improvements.
- ``2`` — at least one checker hit a setup error and no checker has a
  regression/improvement. Hard failures (exit ``1``) take precedence.

Usage:
    python scripts/ratchet.py            # check all ratchets
    python scripts/ratchet.py --update   # rewrite every baseline that can be
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ratchets import coverage, ruff
from ratchets._types import RatchetResult


def _render_stdout(result: RatchetResult) -> str:
    """Format a checker's result for terminal output."""
    lines = [f"=== {result.name} ratchet ==="]
    if result.setup_error:
        lines.append(f"Setup error: {result.setup_error}")
    elif result.regressions:
        lines.append("Ratchet regressions:")
        for change in result.regressions:
            delta = change.new - change.old
            lines.append(f"  {change.metric}: {change.old} -> {change.new} ({delta:+g})")
        lines.append("Either fix the violations or run `just ratchet-update` to bump the baseline.")
    elif result.improvements:
        lines.append("Ratchet improvements:")
        for change in result.improvements:
            delta = change.new - change.old
            lines.append(f"  {change.metric}: {change.old} -> {change.new} ({delta:+g})")
        lines.append("Run `just ratchet-update` to commit the lower baseline.")
    else:
        lines.append("Ratchet OK: baseline matches.")
    return "\n".join(lines)


def _render_summary(result: RatchetResult) -> str:
    """Format a checker's result as a markdown section for ``$GITHUB_STEP_SUMMARY``."""
    lines = [f"### {result.name} ratchet"]
    if result.setup_error:
        lines.append(f"⚠️  Setup error: `{result.setup_error}`")
    elif result.regressions:
        lines.append("**FAIL — regressions:**")
        lines.append("")
        lines.append("| metric | baseline | current | delta |")
        lines.append("|---|---:|---:|---:|")
        for c in result.regressions:
            lines.append(f"| `{c.metric}` | {c.old} | {c.new} | {c.new - c.old:+g} |")
    elif result.improvements:
        lines.append("**Improvements (commit the new baseline):**")
        lines.append("")
        lines.append("| metric | baseline | current | delta |")
        lines.append("|---|---:|---:|---:|")
        for c in result.improvements:
            lines.append(f"| `{c.metric}` | {c.old} | {c.new} | {c.new - c.old:+g} |")
    else:
        lines.append("✅ Baseline matches.")
    return "\n".join(lines) + "\n"


def _write_step_summary(results: list[RatchetResult]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    blocks = [_render_summary(r) for r in results]
    Path(path).open("a", encoding="utf-8").write("\n".join(blocks) + "\n")


def _exit_code(results: list[RatchetResult]) -> int:
    if any(r.has_failure for r in results):
        return 1
    if any(r.setup_error for r in results):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every independent ratchet check.")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite every baseline that can be updated from current state.",
    )
    args = parser.parse_args()

    results = [
        ruff.check(update=args.update),
        coverage.check(update=args.update),
    ]

    for result in results:
        print(_render_stdout(result))
        print()

    _write_step_summary(results)

    if args.update:
        failed = [r.name for r in results if r.setup_error]
        if failed:
            print(f"Could not update: {', '.join(failed)}.")
            return 2
        print("Baselines updated.")
        return 0

    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_orchestrator.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run the orchestrator manually to confirm both checkers run**

Run: `uv run python scripts/ratchet.py`
Expected: prints two `===` blocks (ruff, coverage). Coverage will report a setup error ("coverage.xml not found") since we haven't created the baseline + run `just coverage` yet — that's correct. Exit code will be 2 (assuming ruff is clean) — also correct given current state.

- [ ] **Step 6: Commit**

```bash
git add scripts/ratchet.py tests/scripts/test_orchestrator.py
git commit -m "feat(ratchet): orchestrator runs ruff + coverage with step-summary"
```

---

## Task 9: Update `just check` to use coverage

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Swap `test` for `coverage` in `check`**

In `justfile`, change the `check` recipe (line 6) from:

```just
check: lint format typecheck test ratchet
```

to:

```just
# Check everything: `coverage` runs the test suites under coverage so the
# ratchet has fresh inputs. Fast local loop stays `just test`.
check: lint format typecheck coverage ratchet
```

- [ ] **Step 2: Verify the recipe still resolves**

Run: `just --list --unsorted`
Expected: `check` appears, its dependencies print as `[lint, format, typecheck, coverage, ratchet]`.

(Don't run `just check` yet — there's no coverage baseline, so the coverage checker will report a setup-error and exit non-zero. Task 10 captures the baseline.)

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "chore(just): `check` uses coverage instead of test"
```

---

## Task 10: Capture the initial `.coverage-ratchet.json` baseline

**Files:**
- Create: `.coverage-ratchet.json`

- [ ] **Step 1: Run coverage to produce artifacts**

Run: `just coverage`
Expected: both suites pass; `coverage.xml`, `htmlcov/`, `src/js/web/coverage/coverage-summary.json` all exist.

- [ ] **Step 2: Capture the baseline via the ratchet's update mode**

Run: `just ratchet-update`
Expected: prints `Baselines updated.`; `.coverage-ratchet.json` exists at repo root with all four numbers populated to 2 decimals.

- [ ] **Step 3: Inspect the baseline file**

The file should look roughly like:

```json
{
  "js": {
    "branch": <number>,
    "line": <number>
  },
  "python": {
    "branch": <number>,
    "line": <number>
  }
}
```

- [ ] **Step 4: Verify the ratchet now passes**

Run: `just ratchet`
Expected: both ruff and coverage report `Ratchet OK: baseline matches.`; exit 0.

- [ ] **Step 5: Verify `just check` passes end-to-end**

Run: `just check`
Expected: every step passes; final ratchet check exits 0.

- [ ] **Step 6: Commit the baseline**

```bash
git add .coverage-ratchet.json
git commit -m "chore(ratchet): initial coverage baseline"
```

---

## Task 11: Add the GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - uses: extractions/setup-just@v3

      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version-file: .python-version

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: src/js/web/package-lock.json

      - run: uv sync
      - run: cd src/js/web && npm ci

      - run: just lint
      - run: just typecheck
      - run: just coverage
      - run: just ratchet

      - name: Upload coverage reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-reports
          path: |
            htmlcov/
            coverage.xml
            src/js/web/coverage/
          retention-days: 14
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: first GitHub Actions workflow (lint+typecheck+coverage+ratchet)"
```

- [ ] **Step 3: Push and verify CI runs on the PR**

Run: `git push`
Expected: workflow appears in the PR's Checks tab. The `check` job runs and either passes (commit lands as green) or fails with surfaced output — in either case the job summary contains the two ratchet markdown blocks from the orchestrator.

If the first CI run fails for a workflow reason (not a regression), iterate: edit `.github/workflows/ci.yml`, push, repeat. Workflow self-tests aren't worth chasing locally.

---

## Self-review

### Spec coverage

| Spec section / requirement | Implementing task(s) |
|---|---|
| Both suites emit coverage on every run (local + CI) | Tasks 2, 3, 4, 11 |
| Coverage regressions fail the build via a ratchet | Tasks 7, 8 |
| CI prints a coverage summary to `$GITHUB_STEP_SUMMARY` | Task 8 (`_write_step_summary`), Task 11 (workflow) |
| One `just ratchet` runs every independent ratchet | Task 8 (orchestrator calls both checkers unconditionally) |
| No external services | Confirmed by absence of any external upload step in Task 11 |
| Ratchet baseline in `.coverage-ratchet.json` (4 numbers, 2 decimals) | Tasks 7, 10 |
| `scripts/ratchets/` package with `_types`, `ruff`, `coverage` | Tasks 5, 6, 7 |
| Orchestrator exit codes (`0` clean, `1` failure beats `2` setup error) | Task 8 (`_exit_code` + tests) |
| Coverage checker reads from disk, refuses update if artifacts missing | Task 7 |
| pyproject `[tool.coverage.*]` blocks | Task 2 |
| vite `test.coverage` block | Task 3 |
| justfile `coverage` + `coverage-py` + `coverage-js` recipes | Task 4 |
| `just check` swap `test` → `coverage` | Task 9 |
| `.gitignore` adds `coverage.xml`, `.coverage.*`, `src/js/web/coverage/` | Task 1 |
| `.github/workflows/ci.yml` single-job lint+typecheck+coverage+ratchet | Task 11 |
| Coverage HTML uploaded as artifacts (`if: always()`) | Task 11 |
| Testing strategy: unit tests for coverage checker + orchestrator, no e2e for workflow | Tasks 7, 8 (no Task for workflow self-test, by design) |

No spec requirements left unimplemented.

### Placeholder scan

No `TBD`, `TODO`, `implement later`, or "similar to Task N" placeholders. Every code block is the complete content the engineer pastes.

### Type consistency

- `RatchetResult.regressions` / `improvements` are `tuple[MetricChange, ...]` in Task 5 and used as tuples throughout (Tasks 6, 7, 8). No drift.
- `MetricChange` constructor uses keyword args (`old=`, `new=`) consistently across Tasks 6, 7, and the test fixtures in 7 + 8.
- `coverage.check(...)` signature is identical in Task 7 implementation and Task 7 tests (`baseline_path`, `coverage_xml`, `coverage_summary`, `update`).
- `ruff.check(update=...)` signature is identical between Task 6 and the orchestrator's call in Task 8.
- Orchestrator entry point is `main()` in Tasks 6 and 8, called from `if __name__ == "__main__"`. Tests import `ratchet as orchestrator` and patch `orchestrator.ruff.check` / `orchestrator.coverage.check` — both modules are imported at the top of `scripts/ratchet.py` in Task 8.
