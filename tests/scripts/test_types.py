"""Tests for ``scripts/ratchets/_types``."""

from __future__ import annotations

from ratchets._types import MetricChange, RatchetResult


def test_clean_result_has_no_failure() -> None:
    result = RatchetResult(name="ruff", regressions=(), improvements=())
    assert result.has_failure is False
    assert result.setup_error is None


def test_regression_is_a_failure() -> None:
    result = RatchetResult(
        name="ruff",
        regressions=(MetricChange("PLR0913", old=4, new=5),),
        improvements=(),
    )
    assert result.has_failure is True


def test_improvement_is_a_failure() -> None:
    # Improvements demand an explicit baseline bump — they fail the gate just
    # like regressions, so users notice and run `just ratchet-update`.
    result = RatchetResult(
        name="ruff",
        regressions=(),
        improvements=(MetricChange("PLR0913", old=5, new=4),),
    )
    assert result.has_failure is True


def test_setup_error_alone_is_not_a_failure() -> None:
    result = RatchetResult(
        name="coverage",
        regressions=(),
        improvements=(),
        setup_error="coverage.xml not found",
    )
    assert result.has_failure is False
