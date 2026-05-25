"""CI step-summary emitter.

Each subcommand reads pre-produced tool output, prints GitHub Actions
annotations to stdout (where the runner picks them up), and appends a
markdown table to ``$GITHUB_STEP_SUMMARY``. Reading pre-produced output
rather than invoking the tool keeps the workflow's step granularity
intact — each tool runs as its own step so the run UI shows distinct
timings — and lets ``ci_summary.py`` stay a thin formatter.

Subcommands:

- ``ruff <ruff-json>`` — ``ruff check --output-format=json`` output.
- ``ty <ty-gitlab-json>`` — ``ty check --output-format=gitlab`` output.
- ``pytest <junit-xml> [<coverage-xml>]`` — ``--junit-xml`` from pytest,
  optionally with the Cobertura ``coverage.xml`` for a coverage row.
- ``vitest <junit-xml> [<coverage-summary-json>]`` — vitest's junit
  reporter output, optionally with ``coverage-summary.json``.

Each subcommand exits ``0``. The job's pass/fail is governed by the tool
step that produced the input file, not by this formatter.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO


@contextmanager
def _summary_sink() -> Iterator[TextIO]:
    """Yield the summary sink — ``$GITHUB_STEP_SUMMARY`` or stdout."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        yield sys.stdout
        return
    with Path(path).open("a", encoding="utf-8") as fh:
        yield fh


def _emit(lines: Iterable[str]) -> None:
    with _summary_sink() as fh:
        fh.write("\n".join(lines) + "\n\n")


# ruff


def _annotate_ruff(violations: list[dict]) -> None:
    """Print one ``::error`` annotation per ruff violation."""
    repo_root = Path.cwd()
    for v in violations:
        path = Path(v["filename"])
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            rel = path
        line = v["location"]["row"]
        col = v["location"]["column"]
        code = v["code"]
        message = v["message"].replace("\n", " ")
        print(
            f"::error file={rel},line={line},col={col},title=ruff ({code})::{message}"
        )


def emit_ruff(json_path: Path) -> None:
    raw = json_path.read_text().strip() or "[]"
    violations = json.loads(raw)
    _annotate_ruff(violations)

    counts = Counter(v["code"] for v in violations)
    total = sum(counts.values())

    lines = ["## Ruff lint", ""]
    if total == 0:
        lines.append("| Status |")
        lines.append("|---|")
        lines.append("| Pass — no violations |")
    else:
        lines.append(
            f"**{total} violation{'s' if total != 1 else ''}** "
            "(ratchet gates the count, not this step):"
        )
        lines.append("")
        lines.append("| Rule | Violations |")
        lines.append("|---|---:|")
        for code, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{code}` | {count} |")
    _emit(lines)


# ty


def _annotate_ty(items: list[dict]) -> None:
    """Print one ``::error`` per ty diagnostic (gitlab format)."""
    repo_root = Path.cwd()
    for item in items:
        loc = item.get("location") or {}
        raw_path = loc.get("path", "?")
        path = Path(raw_path)
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            rel = path
        lines = loc.get("lines") or {}
        line = lines.get("begin", 1)
        title = item.get("check_name") or "ty"
        message = (item.get("description") or "").replace("\n", " ")
        print(f"::error file={rel},line={line},title={title}::{message}")


def emit_ty(json_path: Path) -> None:
    raw = json_path.read_text().strip() or "[]"
    items = json.loads(raw)
    _annotate_ty(items)

    per_file = Counter((item.get("location") or {}).get("path", "?") for item in items)
    repo_root = Path.cwd()

    lines = ["## ty typecheck", ""]
    if not items:
        lines.append("| Status |")
        lines.append("|---|")
        lines.append("| Pass — no type errors |")
    else:
        n = len(items)
        f = len(per_file)
        lines.append(
            f"**{n} error{'s' if n != 1 else ''}** in {f} file{'s' if f != 1 else ''}:"
        )
        lines.append("")
        lines.append("| File | Errors |")
        lines.append("|---|---:|")
        for path, count in sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0])):
            try:
                rel = str(Path(path).relative_to(repo_root))
            except ValueError:
                rel = path
            lines.append(f"| `{rel}` | {count} |")
    _emit(lines)


def _parse_junit_totals(junit_path: Path) -> dict[str, int]:
    """Sum ``tests/failures/errors/skipped`` across every ``<testsuite>``."""
    root = ET.parse(junit_path).getroot()  # noqa: S314 — our own output
    suites = list(root.iter("testsuite")) if root.tag != "testsuite" else [root]
    total = failures = errors = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0"))
        errors += int(suite.get("errors", "0"))
        skipped += int(suite.get("skipped", "0"))
    passed = total - failures - errors - skipped
    return {
        "ran": total,
        "passed": passed,
        "failed": failures + errors,
        "skipped": skipped,
    }


def _emit_test_table(heading: str, stats: dict[str, int]) -> list[str]:
    lines = [heading, "", "| Outcome | Count |", "|---|---:|"]
    lines.append(f"| Ran | {stats['ran']} |")
    lines.append(f"| Passed | {stats['passed']} |")
    lines.append(f"| Failed | {stats['failed']} |")
    lines.append(f"| Skipped | {stats['skipped']} |")
    return lines


def _coverage_rows_python(coverage_xml: Path) -> list[str]:
    """Return the markdown rows for a Cobertura ``coverage.xml``."""
    root = ET.parse(coverage_xml).getroot()  # noqa: S314 — our own output
    line_pct = round(float(root.attrib["line-rate"]) * 100)
    branch_pct = round(float(root.attrib["branch-rate"]) * 100)
    return [
        "",
        "### Coverage",
        "",
        "| Metric | Percent |",
        "|---|---:|",
        f"| Line | {line_pct}% |",
        f"| Branch | {branch_pct}% |",
    ]


def _coverage_rows_js(summary_path: Path) -> list[str]:
    """Return coverage rows for the vitest ``coverage-summary.json``."""
    data = json.loads(summary_path.read_text())
    total = data["total"]
    line_pct = round(float(total["lines"]["pct"]))
    branch_pct = round(float(total["branches"]["pct"]))
    return [
        "",
        "### Coverage",
        "",
        "| Metric | Percent |",
        "|---|---:|",
        f"| Line | {line_pct}% |",
        f"| Branch | {branch_pct}% |",
    ]


def emit_pytest(junit_path: Path, coverage_xml: Path | None) -> None:
    stats = _parse_junit_totals(junit_path)
    lines = _emit_test_table("## pytest", stats)
    if coverage_xml and coverage_xml.exists():
        lines.extend(_coverage_rows_python(coverage_xml))
    _emit(lines)


def emit_vitest(junit_path: Path, summary_path: Path | None) -> None:
    stats = _parse_junit_totals(junit_path)
    lines = _emit_test_table("## vitest", stats)
    if summary_path and summary_path.exists():
        lines.extend(_coverage_rows_js(summary_path))
    _emit(lines)


# CLI


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    ruff_p = sub.add_parser("ruff", help="Summarize ruff JSON output.")
    ruff_p.add_argument("json_path", type=Path)

    ty_p = sub.add_parser("ty", help="Summarize ty gitlab-format output.")
    ty_p.add_argument("json_path", type=Path)

    pytest_p = sub.add_parser("pytest", help="Summarize pytest junit + coverage.")
    pytest_p.add_argument("junit_path", type=Path)
    pytest_p.add_argument("coverage_xml", type=Path, nargs="?")

    vitest_p = sub.add_parser("vitest", help="Summarize vitest junit + coverage.")
    vitest_p.add_argument("junit_path", type=Path)
    vitest_p.add_argument("coverage_summary", type=Path, nargs="?")

    args = parser.parse_args()

    if args.cmd == "ruff":
        emit_ruff(args.json_path)
    elif args.cmd == "ty":
        emit_ty(args.json_path)
    elif args.cmd == "pytest":
        emit_pytest(args.junit_path, args.coverage_xml)
    elif args.cmd == "vitest":
        emit_vitest(args.junit_path, args.coverage_summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
