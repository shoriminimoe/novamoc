# Test coverage reporting + first CI workflow

**Status:** Draft
**Date:** 2026-05-24
**Author:** Sam Caldwell

## Problem

Both test suites (`pytest`, `vitest`) run without any coverage instrumentation
and the repo has no CI workflow at all. There is no mechanism that surfaces
"this PR shipped untested code" — neither on the developer's machine nor on
GitHub. Long-term, that erodes confidence in the test suite as a safety net.

## Goals

- Both test suites emit coverage data on every run (local + CI).
- Coverage regressions fail the build via a ratchet, mirroring the existing
  ruff ratchet's "counts only go down" discipline.
- CI prints a human-readable coverage summary to the GitHub Actions job
  summary on every push and PR.
- The ratchet recipe runs **every** independent ratchet (ruff, coverage) on a
  single invocation so a user sees all violations at once.
- Stay self-contained — no Codecov, Coveralls, or other external services
  in v1.

## Non-goals

- README coverage badge (deliberately out of scope; no external service).
- Playwright e2e coverage (browser-instrumented coverage is fiddly; ROI is
  low while the SPA is mostly scaffolding).
- Per-file or per-module ratchet granularity. Per-suite overall % is the
  smallest baseline that catches the regressions we care about.
- Matrix testing (multiple Python versions, multiple Node versions, multiple
  OSes). One ubuntu-latest runner with the project's pinned versions.
- Splitting CI into parallel jobs. v1 is a single sequential job; parallelism
  is a follow-up if total wall time becomes a problem.

## Design

### Tooling choices

- **Python**: `pytest-cov` (the idiomatic pytest pairing for `coverage.py`)
  added as a dev-dep. Branch coverage on via `--cov-branch`. Sources scoped
  to `novamoc` so test files don't pollute the measurement.
- **JavaScript**: `@vitest/coverage-v8` added as a frontend dev-dep. v8's
  native instrumentation is faster than istanbul and ships with vitest. Branch
  coverage on. Reports: `text` (terminal), `html` (local browsing),
  `json-summary` (ratchet input).

Both produce the conventional output paths so downstream tooling stays
plain:

| Suite  | Machine-readable file                            | HTML report          |
|--------|--------------------------------------------------|----------------------|
| Python | `coverage.xml` (Cobertura) at repo root          | `htmlcov/`           |
| JS     | `src/js/web/coverage/coverage-summary.json`      | `src/js/web/coverage/index.html` |

### Ratchet baseline

A single JSON file at the repo root, sibling to `.ruff-ratchet.json`:

```json
{
  "python": { "line": 88.45, "branch": 76.12 },
  "js":     { "line": 65.30, "branch": 58.10 }
}
```

Four numbers, two decimals each. Each can only go up. The two-decimal
granularity lets small improvements register without producing baseline
churn on every PR that adds a single covered line.

### Ratchet orchestration

`scripts/ratchet.py` is refactored from a single-purpose ruff checker into a
thin orchestrator that runs each independent ratchet checker, accumulates
results, and exits with the aggregate status.

```
scripts/
├── ratchet.py              # orchestrator (refactored)
└── ratchets/               # one module per independent ratchet
    ├── __init__.py
    ├── _types.py           # RatchetResult dataclass
    ├── ruff.py             # extracted from current ratchet.py
    └── coverage.py         # new
```

`_types.RatchetResult` carries: a name, a list of regressions (each with a
metric label, old value, new value), a list of improvements (same shape),
and an optional setup-error string for when inputs are missing.

The orchestrator runs every checker **unconditionally** — no fail-fast.
Even if the ruff checker reports regressions, the coverage checker still
runs and reports its own violations. Exit code:

- `0` — every checker clean (no regressions, no improvements, no setup
  errors).
- `1` — at least one checker reports regressions OR improvements. The
  improvements case matches the existing ruff ratchet behaviour: forcing an
  explicit `just ratchet-update` keeps every baseline bump a deliberate
  commit.
- `2` — at least one checker hit a setup error (e.g. missing
  `coverage.xml`) and no checker reported a regression/improvement. Hard
  failures (exit `1`) take precedence — a regression elsewhere is louder
  than a missing-input skip. Every checker still runs and prints either
  way.

The ruff checker's logic is moved verbatim from the current
`scripts/ratchet.py` into `scripts/ratchets/ruff.py`, repackaged as a
function returning `RatchetResult`. Behaviour is unchanged.

The coverage checker reads `coverage.xml` and
`src/js/web/coverage/coverage-summary.json` from disk; it does **not** run
the test suite itself. Producing those artifacts is `just coverage`'s job.
When an artifact is missing, the checker returns a `RatchetResult` with a
setup-error string telling the user to run `just coverage` first; the
orchestrator's other checkers still run normally.

#### `--update` behaviour

`just ratchet-update` runs each checker in update mode. Each checker
refuses to update if its inputs are stale or missing:

- Ruff: re-runs `ruff check` fresh, no staleness concern.
- Coverage: requires both artifact files to exist; refuses (with a clear
  message) if either is missing. Use `just coverage` first.

A partial update is fine when one checker refuses — the other still
updates its baseline. The user can run `just coverage` and re-invoke.

#### GitHub step-summary integration

When the `GITHUB_STEP_SUMMARY` env var is set (i.e. running in Actions),
the orchestrator appends a markdown block to that file as well as printing
to stdout. Each checker contributes its own section. The summary block
contains:

- Per-checker pass / fail line.
- For ruff: a table of regressed rules with `old → new (+delta)`.
- For coverage: a table of all 4 metrics with `baseline / current / delta`,
  highlighting regressions.

### Configuration changes

#### `pyproject.toml`

```toml
[dependency-groups]
dev = [
    # ...existing...
    "pytest-cov>=6.0.0",
]

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

No changes to `[tool.pytest.ini_options]` `addopts` — coverage is opt-in
via `just coverage` rather than baked into every `pytest` invocation, so
`just test` stays fast.

#### `src/js/web/vite.config.ts`

The existing `test:` block grows a `coverage:` sub-block:

```ts
test: {
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

#### `src/js/web/package.json`

```json
"devDependencies": {
  "@vitest/coverage-v8": "^4.1.6",
  ...
}
```

The `test` script stays as `vitest run`; coverage is opt-in via
`vitest run --coverage` from the justfile recipe.

### Justfile changes

```just
# Test everything (fast, uncovered) — unchanged
[parallel]
test: test-py test-js

# Run both test suites under coverage and write artifacts
[parallel]
coverage: coverage-py coverage-js

coverage-py:
    uv run pytest --cov --cov-branch --cov-report=xml --cov-report=html --cov-report=term

coverage-js:
    cd src/js/web && npm run test -- --coverage

# Check every independent ratchet (ruff + coverage)
ratchet:
    uv run python scripts/ratchet.py

# Update every independent ratchet baseline from current state
ratchet-update:
    uv run python scripts/ratchet.py --update

# Check everything — swaps `test` for `coverage` so ratchet has inputs
check: lint format typecheck coverage ratchet
```

`just check` slows by the coverage overhead (~20–30% on each suite) but
gains comprehensive ratchet enforcement. The fast local loop is
`just test`, unchanged.

### CI workflow

Single workflow `.github/workflows/ci.yml`. Triggered on push to `main`
and on any pull request. One job, sequential steps:

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
          cache: 'npm'
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

The `if: always()` on the upload step ensures coverage reports are still
available even when the ratchet job fails — that's the case where the
reports are most useful for diagnosis.

The job summary is populated by the orchestrator
(`scripts/ratchet.py`) writing to `$GITHUB_STEP_SUMMARY` as described
above. No separate "write summary" step is needed.

### Gitignore additions

The current `.gitignore` already covers `.coverage` and `htmlcov/`. Add:

- `coverage.xml`
- `.coverage.*` (for parallel `coverage run` data files, if added later)
- `src/js/web/coverage/`

### Initial baseline

The first commit lands `.coverage-ratchet.json` with the values measured
on `main` at the time the spec ships. This may show as 0% for files newly
added by this PR (e.g. `scripts/ratchets/coverage.py` itself); that is
intentional — the spec doesn't require self-coverage as part of the
shipping criteria, only that the ratchet captures *some* baseline. The
follow-up to add unit tests for the ratchet checker can land separately.

## Testing strategy

Three layers, smallest layer that proves the behaviour each time:

1. **Unit tests for the coverage checker.** Feed
   `scripts/ratchets/coverage.py` synthetic `coverage.xml` /
   `coverage-summary.json` fixtures (small hand-written files under
   `tests/scripts/data/`) and assert the `RatchetResult` it returns for
   the regression / improvement / clean / setup-error cases.
2. **Unit test for the orchestrator.** Inject fake checkers and assert
   aggregate exit codes, GitHub-step-summary markdown shape, and that
   every checker runs even when an earlier one fails.
3. **No e2e test for the CI workflow itself.** The first push to a PR
   branch validates it. If the workflow breaks, the next push fixes it.
   Spending lint-time on a self-test of the workflow file isn't worth the
   complexity.

Existing tests are not affected — `just test` remains the fast,
uncovered path.

## Migration / rollout

1. Land the tooling + refactored ratchet orchestrator + coverage checker
   first, with a stub `.coverage-ratchet.json` initialised from
   `just coverage` output on `main`.
2. Land the CI workflow next, after the local `just check` flow is known
   green.
3. Once both have landed, subsequent PRs are gated by the ratchet
   automatically — no migration tooling for callers, no transition
   period, no deprecation shims (pre-release status).

## Open questions

None blocking.

## Alternatives considered

- **Codecov / Coveralls.** Rejected per user direction — no external
  services in v1.
- **Self-hosted shields.io badge via a gh-pages branch.** Rejected as
  badge-out-of-scope; this is a follow-up if a badge is ever wanted.
- **Multi-job CI (parallel python + js).** Adds complexity (artifact
  upload/download between jobs) for marginal wall-time savings on a
  test suite that currently runs in seconds. Single-job is the right
  starting point.
- **Per-file or per-module ratchet granularity.** Would catch
  regressions a single-number overall ratchet misses, at the cost of
  baseline churn on every PR. Overall % per suite + branch tracking is
  the smallest baseline that catches what we care about.
- **Bake `--cov` into `addopts`.** Would slow every local `pytest`
  invocation. Keeping coverage opt-in via `just coverage` preserves
  fast local iteration.
- **A single coverage tool spanning both languages (e.g. trace via
  `pytest --cov` + manual JS instrumentation).** Each ecosystem has a
  native, well-supported tool; the cost of unifying them outweighs the
  cost of maintaining two side-by-side configurations.
