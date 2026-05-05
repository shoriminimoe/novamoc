"""Ruff violation ratchet.

Tracks per-rule violation counts in ``.ruff-ratchet.json``. The build fails
when any rule's count goes up. When counts go down, the script reports the
improvement and exits non-zero asking for an explicit baseline update — that
keeps every step of the ratchet a deliberate commit rather than a silent
side-effect.

Usage:
    python scripts/ratchet.py            # check current counts vs baseline
    python scripts/ratchet.py --update   # rewrite the baseline from current state

The baseline is committed to the repo. ``ruff check --fix`` should run before
this script (``just lint-py`` already does so), so only non-auto-fixable
violations end up in the ratchet.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / ".ruff-ratchet.json"


def current_counts() -> dict[str, int]:
    """Return ``{rule_code: count}`` from a fresh ``ruff check`` run."""
    # `uv` is required to be on PATH; this script is dev-only.
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "--no-fix", "--output-format=json", "."],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # ruff exits non-zero whenever violations exist; that's expected. We only
    # bail if it fails to produce parseable JSON (config error, crash, etc.).
    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write("ratchet: failed to parse ruff output\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        sys.exit(2)
    return dict(Counter(v["code"] for v in violations))


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text())


def write_baseline(counts: dict[str, int]) -> None:
    payload = json.dumps(counts, indent=2, sort_keys=True) + "\n"
    BASELINE.write_text(payload)


def diff(
    baseline: dict[str, int], current: dict[str, int]
) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    """Return (regressions, improvements) as lists of (code, old, new)."""
    rules = set(baseline) | set(current)
    regressions: list[tuple[str, int, int]] = []
    improvements: list[tuple[str, int, int]] = []
    for rule in sorted(rules):
        old = baseline.get(rule, 0)
        new = current.get(rule, 0)
        if new > old:
            regressions.append((rule, old, new))
        elif new < old:
            improvements.append((rule, old, new))
    return regressions, improvements


def main() -> int:
    parser = argparse.ArgumentParser(description="Ruff violation ratchet.")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the baseline from the current ruff state.",
    )
    args = parser.parse_args()

    current = current_counts()

    if args.update:
        write_baseline(current)
        total = sum(current.values())
        rules = len(current)
        print(f"Baseline updated: {total} violations across {rules} rules.")
        return 0

    if not BASELINE.exists():
        sys.stderr.write(
            f"No ratchet baseline at {BASELINE.relative_to(REPO_ROOT)}.\n"
            "Run `just ratchet-update` to create one.\n"
        )
        return 2

    baseline = load_baseline()
    regressions, improvements = diff(baseline, current)

    if regressions:
        print("Ratchet regressions (new violations):")
        for code, old, new in regressions:
            print(f"  {code}: {old} -> {new} (+{new - old})")
        print()
        print("Either fix the new violations or, if intentional, run")
        print("`just ratchet-update` to bump the baseline.")
        return 1

    if improvements:
        print("Ratchet improvements:")
        for code, old, new in improvements:
            print(f"  {code}: {old} -> {new} (-{old - new})")
        print()
        print("Run `just ratchet-update` to commit the lower baseline.")
        return 1

    total = sum(current.values())
    print(f"Ratchet OK: {total} violations, baseline matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
