"""Tests for the build-time markdown → HTML render script.

Endpoint-level coverage is added in a later task once the markdown
sources exist. These tests pin the script's contract: how it discovers
codes, how it validates inputs, what HTML it produces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from render_problem_docs import _default_src_dir, render_all, render_one

from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.api._problem_details import _TITLES
from novamoc.domain._errors import ErrorCode

if TYPE_CHECKING:
    from pathlib import Path

    from litestar.testing import AsyncTestClient


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


@pytest.mark.parametrize("code", sorted(PROBLEM_CODES))
async def test_problem_doc_endpoint_serves_html(
    client: AsyncTestClient, code: str
) -> None:
    response = await client.get(f"/problems/{code}.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    expected_title = (
        _TITLES[ErrorCode(code)]
        if code != "tenant_not_resolved"
        else "Tenant not resolved"
    )
    assert expected_title in response.text


async def test_problem_doc_endpoint_does_not_require_auth(
    client: AsyncTestClient,
) -> None:
    # Override the default Bearer the client fixture sets on the
    # underlying httpx client. /problems/* should be reachable without
    # credentials because the auth middleware excludes the prefix.
    response = await client.get(
        "/problems/name_reserved.html",
        headers={"Authorization": ""},
    )
    assert response.status_code == 200


async def test_unknown_problem_doc_returns_404(
    client: AsyncTestClient,
) -> None:
    response = await client.get("/problems/does_not_exist.html")
    assert response.status_code == 404


async def test_problem_type_uri_dereferences_to_doc(
    client: AsyncTestClient,
) -> None:
    """Trigger a real error path, parse the type URI, fetch it, expect 200.

    Integration-level proof that the URN-to-URL swap closes the loop the
    issue is about: clients can follow the `type` field to reachable
    docs.
    """
    # Provoke a name_reserved by creating two asset types with the same
    # name. POST /schema's wire shape is {type, entity_id, payload}; the
    # tenant comes from the Bearer token, not the body (ADR-017).
    name = f"DuplicateMe-{uuid4()}"
    body = {
        "type": "create_asset_type",
        "entity_id": str(uuid4()),
        "payload": {"name": name},
    }
    first = await client.post("/schema", json=body)
    assert first.status_code in (200, 201), first.text
    body["entity_id"] = str(uuid4())
    second = await client.post("/schema", json=body)
    assert second.status_code == 409, second.text
    err = second.json()
    type_uri = err["type"]
    assert type_uri == "http://test/problems/name_reserved.html"

    # AsyncTestClient is rooted at the app, so we re-fetch with the path
    # only — the host part of `type` is just the configured base URL.
    path = urlparse(type_uri).path
    assert path == "/problems/name_reserved.html"
    follow = await client.get(path)
    assert follow.status_code == 200
    assert "Name reserved" in follow.text


def test_every_code_has_a_doc_file() -> None:
    """Static check independent of any HTTP layer.

    The render script enforces the same property at build time; this
    mirror inside the test suite catches a missing or orphan markdown
    file before any HTTP-layer test runs.
    """
    src_dir = _default_src_dir()
    found = {p.stem for p in src_dir.glob("*.md")}
    assert found == set(PROBLEM_CODES)
