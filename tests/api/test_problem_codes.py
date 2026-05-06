from __future__ import annotations

from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.domain.schema._errors import ErrorCode


def test_problem_codes_includes_every_error_code_member() -> None:
    for code in ErrorCode:
        assert code.value in PROBLEM_CODES


def test_problem_codes_includes_tenant_not_resolved() -> None:
    assert "tenant_not_resolved" in PROBLEM_CODES


def test_problem_codes_is_a_frozenset() -> None:
    assert isinstance(PROBLEM_CODES, frozenset)
