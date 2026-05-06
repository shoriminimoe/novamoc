from __future__ import annotations

from typing import TYPE_CHECKING

from novamoc.config import problem_docs_base_url

if TYPE_CHECKING:
    import pytest


def test_problem_docs_base_url_defaults_to_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", raising=False)
    assert problem_docs_base_url() == "http://localhost:8000"


def test_problem_docs_base_url_reads_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "https://docs.example.com")
    assert problem_docs_base_url() == "https://docs.example.com"
