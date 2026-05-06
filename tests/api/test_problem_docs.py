"""Tests for the build-time markdown → HTML render script.

Endpoint-level coverage is added in a later task once the markdown
sources exist. These tests pin the script's contract: how it discovers
codes, how it validates inputs, what HTML it produces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from render_problem_docs import render_all, render_one

if TYPE_CHECKING:
    from pathlib import Path


def test_render_one_wraps_body_with_html5_doctype_and_title() -> None:
    body_md = "Body text.\n\n## Subhead\n\nMore prose.\n"
    html = render_one(title="Name reserved", body_markdown=body_md)
    assert html.startswith(("<!doctype html>", "<!DOCTYPE html>"))
    assert "<title>Name reserved</title>" in html
    assert "<h1>Name reserved</h1>" in html
    assert "<h2>Subhead</h2>" in html
    assert "<p>Body text.</p>" in html


def test_render_one_inline_styles_no_external_assets() -> None:
    html = render_one(title="X", body_markdown="hello\n")
    assert "<style>" in html
    assert "<link" not in html
    assert "<script" not in html


def test_render_all_writes_one_html_per_code(tmp_path: Path) -> None:
    src = tmp_path / "docs"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    expected = frozenset({"name_reserved", "tenant_not_resolved"})
    titles = {
        "name_reserved": "Name reserved",
        "tenant_not_resolved": "Tenant not resolved",
    }
    (src / "name_reserved.md").write_text("Name body.\n", encoding="utf-8")
    (src / "tenant_not_resolved.md").write_text("Tenant body.\n", encoding="utf-8")

    render_all(src_dir=src, out_dir=out, expected_codes=expected, titles=titles)

    assert (out / "name_reserved.html").is_file()
    assert (out / "tenant_not_resolved.html").is_file()
    assert "<title>Name reserved</title>" in (out / "name_reserved.html").read_text()


def test_render_all_fails_on_missing_doc(tmp_path: Path) -> None:
    src = tmp_path / "docs"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    expected = frozenset({"name_reserved"})
    titles = {"name_reserved": "Name reserved"}

    with pytest.raises(SystemExit) as excinfo:
        render_all(src_dir=src, out_dir=out, expected_codes=expected, titles=titles)
    assert excinfo.value.code != 0


def test_render_all_fails_on_orphan_doc(tmp_path: Path) -> None:
    src = tmp_path / "docs"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "name_reserved.md").write_text("ok\n", encoding="utf-8")
    (src / "extra.md").write_text("orphan\n", encoding="utf-8")
    expected = frozenset({"name_reserved"})
    titles = {"name_reserved": "Name reserved"}

    with pytest.raises(SystemExit) as excinfo:
        render_all(src_dir=src, out_dir=out, expected_codes=expected, titles=titles)
    assert excinfo.value.code != 0


def test_render_all_overwrites_existing_html(tmp_path: Path) -> None:
    src = tmp_path / "docs"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "name_reserved.md").write_text("first\n", encoding="utf-8")
    (out / "name_reserved.html").write_text("stale", encoding="utf-8")

    render_all(
        src_dir=src,
        out_dir=out,
        expected_codes=frozenset({"name_reserved"}),
        titles={"name_reserved": "Name reserved"},
    )
    contents = (out / "name_reserved.html").read_text()
    assert "stale" not in contents
    assert "<p>first</p>" in contents
