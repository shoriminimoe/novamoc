"""Build-time markdown → HTML renderer for problem-details docs.

Reads ``docs/problems/<code>.md``, wraps each body in a small HTML5
template, writes ``build/wheel_data/novamoc/html/<code>.html``. Run via
``just render-problem-docs`` (= ``uv run python scripts/render_problem_docs.py``);
``just build-py`` and ``just serve`` depend on it.

The renderer lives outside the package so it does not ride along into
the installed wheel — ``markdown-it-py`` is a build-time dependency
only. Output goes under ``build/`` (the standard Python build-artifact
directory, already gitignored). The inner layout mirrors the install
path so uv_build's ``[tool.uv.build-backend.data]`` ``purelib`` scheme
ships the rendered HTML directly into ``<site-packages>/novamoc/html/``
in a wheel install. Runtime resolution lives in ``novamoc.config`` (it
falls back to the build-artifact tree for editable installs, where
wheel data is not materialized).

Failure modes are loud and bidirectional: a code without a doc and a
doc without a code both exit non-zero. ``render_all()`` is also called
from the test suite, so CI catches drift the moment a code is added
without its doc.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from novamoc.api._problem_codes import PROBLEM_CODES
from novamoc.api._problem_details import _TITLES
from novamoc.domain._errors import ErrorCode

if TYPE_CHECKING:
    from collections.abc import Mapping

_md = MarkdownIt("commonmark")


# Inline so we ship no external CSS/JS assets — the page is dev-facing
# and needs to be readable in a browser without a build pipeline.
_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
                 sans-serif;
    line-height: 1.5;
    max-width: 70ch;
    margin: 2rem auto;
    padding: 0 1rem;
    color: #1a1a1a;
  }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0.4rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 1.6rem; }}
  code {{
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    background: #f4f4f4;
    padding: 0.1em 0.3em;
    border-radius: 3px;
  }}
  pre code {{ background: transparent; padding: 0; }}
  pre {{
    background: #f4f4f4;
    padding: 0.8em 1em;
    border-radius: 4px;
    overflow-x: auto;
  }}
  a {{ color: #0366d6; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
{body}
</main>
</body>
</html>
"""


def render_one(*, title: str, body_markdown: str) -> str:
    body_html = _md.render(body_markdown)
    return _HTML_TEMPLATE.format(title=title, body=body_html)


def render_all(
    *,
    src_dir: Path,
    out_dir: Path,
    expected_codes: frozenset[str],
    titles: Mapping[str, str],
) -> None:
    found = {p.stem for p in src_dir.glob("*.md")}
    missing = expected_codes - found
    orphans = found - expected_codes
    if missing or orphans:
        msg_parts: list[str] = []
        if missing:
            msg_parts.append(f"missing docs for codes: {sorted(missing)}")
        if orphans:
            msg_parts.append(
                f"orphan markdown files (no matching code): {sorted(orphans)}"
            )
        sys.stderr.write("render_problem_docs: " + "; ".join(msg_parts) + "\n")
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    for code in sorted(expected_codes):
        body_md = (src_dir / f"{code}.md").read_text(encoding="utf-8")
        title = titles[code]
        html = render_one(title=title, body_markdown=body_md)
        (out_dir / f"{code}.html").write_text(html, encoding="utf-8")


def _default_titles() -> dict[str, str]:
    titles: dict[str, str] = {c.value: _TITLES[c] for c in ErrorCode}
    titles["tenant_not_resolved"] = "Tenant not resolved"
    return titles


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_src_dir() -> Path:
    return _REPO_ROOT / "docs" / "problems"


def _default_out_dir() -> Path:
    # Layout mirrors the wheel install path so uv_build's purelib data
    # scheme ships <site-packages>/novamoc/html/<code>.html.
    return _REPO_ROOT / "build" / "wheel_data" / "novamoc" / "html"


def main() -> None:
    render_all(
        src_dir=_default_src_dir(),
        out_dir=_default_out_dir(),
        expected_codes=PROBLEM_CODES,
        titles=_default_titles(),
    )


if __name__ == "__main__":
    main()
