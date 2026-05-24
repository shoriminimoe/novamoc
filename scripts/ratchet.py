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
from typing import TYPE_CHECKING

from ratchets import coverage, ruff

if TYPE_CHECKING:
    from ratchets._types import RatchetResult


def _render_stdout(result: RatchetResult) -> str:
    """Format a checker's result for terminal output."""
    lines = [f"=== {result.name} ratchet ==="]
    if result.setup_error:
        lines.append(f"Setup error: {result.setup_error}")
    elif result.regressions:
        lines.append("Ratchet regressions:")
        lines.extend(
            f"  {c.metric}: {c.old} -> {c.new} ({c.new - c.old:+g})"
            for c in result.regressions
        )
        lines.append(
            "Either fix the violations or run"
            " `just ratchet-update` to bump the baseline."
        )
    elif result.improvements:
        lines.append("Ratchet improvements:")
        lines.extend(
            f"  {c.metric}: {c.old} -> {c.new} ({c.new - c.old:+g})"
            for c in result.improvements
        )
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
        lines.extend(
            f"| `{c.metric}` | {c.old} | {c.new} | {c.new - c.old:+g} |"
            for c in result.regressions
        )
    elif result.improvements:
        lines.append("**Improvements (commit the new baseline):**")
        lines.append("")
        lines.append("| metric | baseline | current | delta |")
        lines.append("|---|---:|---:|---:|")
        lines.extend(
            f"| `{c.metric}` | {c.old} | {c.new} | {c.new - c.old:+g} |"
            for c in result.improvements
        )
    else:
        lines.append("✅ Baseline matches.")
    return "\n".join(lines) + "\n"


def _write_step_summary(results: list[RatchetResult]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    blocks = [_render_summary(r) for r in results]
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write("\n".join(blocks) + "\n")


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
