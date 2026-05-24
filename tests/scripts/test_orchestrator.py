"""Tests for the ratchet orchestrator's aggregation logic."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

# Import the script as a module — ``scripts/`` is on pythonpath.
import ratchet as orchestrator
from ratchets._types import MetricChange, RatchetResult

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
    return RatchetResult(
        name=name, regressions=(), improvements=(), setup_error="missing"
    )


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


def test_main_runs_every_checker_even_when_one_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(orchestrator.ruff, "check", return_value=_regressed("ruff")),
        patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")),
        patch.object(sys, "argv", ["ratchet.py"]),
    ):
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
    with (
        patch.object(orchestrator.ruff, "check", return_value=_regressed("ruff")),
        patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")),
        patch.object(sys, "argv", ["ratchet.py"]),
    ):
        orchestrator.main()
    md = summary_path.read_text()
    assert "ruff" in md
    assert "coverage" in md
    # Regressed checker should be flagged in the summary.
    assert "FAIL" in md or "regress" in md.lower()


def test_step_summary_skipped_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with (
        patch.object(orchestrator.ruff, "check", return_value=_clean("ruff")),
        patch.object(orchestrator.coverage, "check", return_value=_clean("coverage")),
        patch.object(sys, "argv", ["ratchet.py"]),
    ):
        rc = orchestrator.main()
    # No env, no file — nothing to assert beyond "didn't crash".
    assert rc == 0
