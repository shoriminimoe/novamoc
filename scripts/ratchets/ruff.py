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
