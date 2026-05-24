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
DEFAULT_JS_SUMMARY = (
    REPO_ROOT / "src" / "js" / "web" / "coverage" / "coverage-summary.json"
)


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
    line = round(float(total["lines"]["pct"]), 2)
    branch = round(float(total["branches"]["pct"]), 2)
    return line, branch


def _load_baseline(path: Path) -> dict[str, dict[str, float]]:
    return json.loads(path.read_text())


def _write_baseline(
    path: Path, py: tuple[float, float], js: tuple[float, float]
) -> None:
    payload = {
        "python": {"line": py[0], "branch": py[1]},
        "js": {"line": js[0], "branch": js[1]},
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
            setup_error="coverage.xml not found. Run `just coverage` first.",
        )
    if not coverage_summary.exists():
        return RatchetResult(
            name="coverage",
            regressions=(),
            improvements=(),
            setup_error="coverage-summary.json not found. Run `just coverage` first.",
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
                "No baseline at .coverage-ratchet.json. "
                "Run `just ratchet-update` to create one."
            ),
        )

    baseline = _load_baseline(baseline_path)
    current: dict[str, dict[str, float]] = {
        "python": {"line": py[0], "branch": py[1]},
        "js": {"line": js[0], "branch": js[1]},
    }
    regressions, improvements = _diff(baseline, current)
    return RatchetResult(
        name="coverage",
        regressions=regressions,
        improvements=improvements,
    )
