"""Tests for the CI step-summary emitter.

Exercises the four subcommands by feeding hand-written tool-output
fixtures into the module-level emit functions, then asserts on the
captured stdout (annotations) and the markdown written to
``GITHUB_STEP_SUMMARY``. Real tool runs are exercised by CI itself; the
unit-level concern is the parser-to-markdown contract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import ci_summary

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _read_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``GITHUB_STEP_SUMMARY`` at a tmp file and return its path."""
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    return summary


def test_ruff_clean_emits_pass_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    ruff_json = tmp_path / "ruff.json"
    ruff_json.write_text("[]")

    ci_summary.emit_ruff(ruff_json)

    md = summary.read_text()
    assert "## Ruff lint" in md
    assert "Pass — no violations" in md
    # No annotations on a clean run.
    assert capsys.readouterr().out == ""


def test_ruff_violations_table_groups_by_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    ruff_json = tmp_path / "ruff.json"
    ruff_json.write_text(
        json.dumps(
            [
                {
                    "code": "E501",
                    "message": "Line too long",
                    "filename": str(tmp_path / "a.py"),
                    "location": {"row": 1, "column": 89},
                },
                {
                    "code": "E501",
                    "message": "Line too long",
                    "filename": str(tmp_path / "b.py"),
                    "location": {"row": 7, "column": 89},
                },
                {
                    "code": "PLC0415",
                    "message": "import",
                    "filename": str(tmp_path / "c.py"),
                    "location": {"row": 3, "column": 5},
                },
            ]
        )
    )

    ci_summary.emit_ruff(ruff_json)

    md = summary.read_text()
    assert "**3 violations**" in md
    assert "| `E501` | 2 |" in md
    assert "| `PLC0415` | 1 |" in md
    # E501 (2) sorts before PLC0415 (1).
    assert md.index("E501") < md.index("PLC0415")

    annotations = capsys.readouterr().out.splitlines()
    assert len(annotations) == 3
    assert all(line.startswith("::error ") for line in annotations)
    assert any("title=ruff (E501)" in line for line in annotations)


def test_ty_clean_emits_pass_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    ty_json = tmp_path / "ty.json"
    ty_json.write_text("[]")

    ci_summary.emit_ty(ty_json)

    md = summary.read_text()
    assert "## ty typecheck" in md
    assert "Pass — no type errors" in md


def test_ty_errors_table_groups_by_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Make cwd match the fixture root so relative_to(...) finds the prefix.
    monkeypatch.chdir(tmp_path)
    summary = _read_summary(monkeypatch, tmp_path)
    ty_json = tmp_path / "ty.json"
    ty_json.write_text(
        json.dumps(
            [
                {
                    "check_name": "no-matching-overload",
                    "description": "argument mismatch",
                    "location": {
                        "path": str(tmp_path / "a.py"),
                        "lines": {"begin": 12},
                    },
                },
                {
                    "check_name": "no-matching-overload",
                    "description": "another mismatch",
                    "location": {
                        "path": str(tmp_path / "a.py"),
                        "lines": {"begin": 30},
                    },
                },
                {
                    "check_name": "unresolved-attr",
                    "description": "missing attr",
                    "location": {
                        "path": str(tmp_path / "b.py"),
                        "lines": {"begin": 1},
                    },
                },
            ]
        )
    )

    ci_summary.emit_ty(ty_json)

    md = summary.read_text()
    assert "**3 errors** in 2 files" in md
    assert "| `a.py` | 2 |" in md
    assert "| `b.py` | 1 |" in md

    annotations = capsys.readouterr().out.splitlines()
    assert len(annotations) == 3
    assert all(line.startswith("::error ") for line in annotations)


def _write_pytest_junit(path: Path, *, tests: int, failures: int, skipped: int) -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="{tests}" failures="{failures}" errors="0"
             skipped="{skipped}" time="1.0"/>
</testsuites>
"""
    )


def test_pytest_summary_without_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    junit = tmp_path / "pytest-junit.xml"
    _write_pytest_junit(junit, tests=100, failures=2, skipped=3)

    ci_summary.emit_pytest(junit, None)

    md = summary.read_text()
    assert "## pytest" in md
    assert "| Ran | 100 |" in md
    assert "| Passed | 95 |" in md
    assert "| Failed | 2 |" in md
    assert "| Skipped | 3 |" in md
    assert "### Coverage" not in md


def test_pytest_summary_with_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    junit = tmp_path / "pytest-junit.xml"
    _write_pytest_junit(junit, tests=10, failures=0, skipped=0)
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        '<?xml version="1.0" ?><coverage line-rate="0.8845" branch-rate="0.7612"/>'
    )

    ci_summary.emit_pytest(junit, coverage_xml)

    md = summary.read_text()
    assert "### Coverage" in md
    assert "| Line | 88% |" in md
    assert "| Branch | 76% |" in md


def test_vitest_summary_with_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _read_summary(monkeypatch, tmp_path)
    junit = tmp_path / "vitest-junit.xml"
    _write_pytest_junit(junit, tests=52, failures=1, skipped=0)
    summary_json = tmp_path / "coverage-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "total": {
                    "lines": {"pct": 71.4},
                    "branches": {"pct": 52.1},
                }
            }
        )
    )

    ci_summary.emit_vitest(junit, summary_json)

    md = summary.read_text()
    assert "## vitest" in md
    assert "| Ran | 52 |" in md
    assert "| Failed | 1 |" in md
    assert "| Line | 71% |" in md
    assert "| Branch | 52% |" in md


def test_junit_parser_aggregates_multiple_testsuites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Top-level ``<testsuites>`` counts can sit on nested ``<testsuite>``s instead."""
    summary = _read_summary(monkeypatch, tmp_path)
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="a" tests="5" failures="1" errors="0" skipped="0"/>
  <testsuite name="b" tests="3" failures="0" errors="1" skipped="2"/>
</testsuites>
"""
    )

    ci_summary.emit_pytest(junit, None)

    md = summary.read_text()
    assert "| Ran | 8 |" in md
    assert "| Passed | 4 |" in md
    assert "| Failed | 2 |" in md
    assert "| Skipped | 2 |" in md
