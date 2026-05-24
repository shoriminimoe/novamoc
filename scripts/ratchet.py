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
from typing import TYPE_CHECKING

from ratchets import ruff

if TYPE_CHECKING:
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
