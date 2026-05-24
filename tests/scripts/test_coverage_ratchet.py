"""Tests for ``scripts/ratchets/coverage``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ratchets import coverage as cov_ratchet

FIXTURES = Path(__file__).parent / "data"
CLEAN_XML = FIXTURES / "coverage_clean.xml"
CLEAN_JSON = FIXTURES / "coverage_summary_clean.json"


def _baseline(
    tmp_path: Path,
    *,
    py_line: float,
    py_branch: float,
    js_line: float,
    js_branch: float,
) -> Path:
    path = tmp_path / ".coverage-ratchet.json"
    path.write_text(
        json.dumps(
            {
                "python": {"line": py_line, "branch": py_branch},
                "js": {"line": js_line, "branch": js_branch},
            },
            indent=2,
        )
        + "\n"
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
    baseline = _baseline(
        tmp_path, py_line=88.45, py_branch=76.12, js_line=65.30, js_branch=58.10
    )
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
    baseline = _baseline(
        tmp_path, py_line=90.00, py_branch=76.12, js_line=65.30, js_branch=58.10
    )
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
    baseline = _baseline(
        tmp_path, py_line=88.45, py_branch=76.12, js_line=65.30, js_branch=55.00
    )
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
        "js": {"line": pytest.approx(65.30), "branch": pytest.approx(58.10)},
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
