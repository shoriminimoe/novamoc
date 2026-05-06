# Per-code problem-details documentation endpoint

Closes #13.

## Problem

ADR-016 left the type URI for every problem-details response as an opaque,
non-reachable URN (`urn:novamoc:problems:<code>`). The leaf segment is the
stable contract; the host is non-breaking and was deliberately deferred until
real documentation existed. Issue #13 tracks replacing it with an HTTPS URL
that dereferences to per-code documentation.

## Scope and framing

This is an **interim** capability. The novaMOC API hosts the docs today so the
URN goes away, but the medium-term plan is a separate static docs site (e.g.
`docs.novamoc.app`). Three consequences:

* The runtime surface is deliberately small. No on-the-fly markdown rendering,
  no in-memory cache, no asset pipeline.
* Source markdown lives under `docs/problems/`, not inside the package, so
  retiring this endpoint later is a `git mv` rather than fishing files out of
  the package.
* The configurable type-URI base lets the same wire contract point at
  whatever host eventually serves the docs without code changes.

## Architecture

```
docs/problems/<code>.md             ← editable source, plain markdown
        │
        │  rendered by `just render-problem-docs`
        │  (= uv run python -m novamoc.scripts.render_problem_docs)
        ▼
src/py/novamoc/api/_problem_html/   ← gitignored; under uv_build module-root
       └── <code>.html                so it rides into the wheel
        │
        │  served by Litestar create_static_files_router(html_mode=True)
        ▼
GET /problems/<code>                  →  200 text/html

<base>/problems/<code>                →  type URI in problem-details responses
                                          <base> = NOVAMOC_PROBLEM_DOCS_BASE_URL
```

## Build-time rendering

`uv_build` (the project's build backend) is intentionally minimal and exposes
no PEP 517 hook extension mechanism. Rather than switch backends, the
justfile orchestrates the render before `uv build`:

```
render-problem-docs:
    uv run python -m novamoc.scripts.render_problem_docs

build-py: render-problem-docs
    uv build

serve: render-problem-docs
    uv run litestar --app novamoc.asgi:create_app run

clean:
    rm -rf dist src/py/novamoc/api/_problem_html
```

Adding `serve: render-problem-docs` keeps the dev loop self-healing — a fresh
checkout or post-`clean` state still produces rendered HTML before the server
boots. The render script needs `src/py/novamoc/scripts/__init__.py` (empty)
so `python -m novamoc.scripts.render_problem_docs` resolves.

`markdown-it-py` is added to `[dependency-groups.dev]` only — it is a
build-time dependency. The runtime wheel ships pre-rendered HTML, so the
runtime never imports a markdown library.

The render script (`src/py/novamoc/scripts/render_problem_docs.py`):

1. Computes `expected = PROBLEM_CODES`, `found = {p.stem for p in docs/problems/*.md}`.
2. Fails fast if `expected != found`. Missing-doc and orphan-doc are both
   errors. CI catches both.
3. For each code: read `docs/problems/<code>.md`, render with
   `markdown-it-py` (commonmark profile, no plugins), wrap in the HTML
   template, write to `<package>/api/_problem_html/<code>.html`.
4. Title for `<title>` and the wrapper's `<h1>` comes from `_TITLES[code]` —
   the same string the wire `title` field carries. Markdown holds prose only,
   so there is one source of truth per concern.

## Canonical code list

A new module unifies the set of known problem codes:

```python
# src/py/novamoc/api/_problem_codes.py
from novamoc.domain.schema._errors import ErrorCode

PROBLEM_CODES: frozenset[str] = frozenset(
    {c.value for c in ErrorCode} | {"tenant_not_resolved"}
)
```

`_problem_details.py`, the render script, and the test suite import from
here. Adding a non-enum code (the way `tenant_not_resolved` did) is one line.

## Markdown convention

Each `docs/problems/<code>.md` is body-only — no frontmatter, no top-level
H1. The render wrapper supplies the page title from `_TITLES[code]`. Soft
convention for the body:

```markdown
The same name is already in use.

## Common causes

- Two clients tried to create the same asset type concurrently.
- ...

## How to fix

- ...

## Related

- `parent_type_not_found`
```

The render script enforces existence and successful rendering, not body
shape. Authors are free to deviate.

## HTML wrapper

A single template string (~40 lines) inlined in the render script:

* HTML5 doctype, `<meta charset>`, `<meta viewport>`.
* `<title>` from `_TITLES[code]`.
* Inline `<style>` block: system font stack, ~70ch max-width, modest heading
  sizes, monospace code blocks. No external assets, no JavaScript.
* `<main>` containing `<h1>{title}</h1>` followed by the rendered markdown.

## Runtime wiring

`novamoc/config.py` (currently empty) gains one helper:

```python
import os
def problem_docs_base_url() -> str:
    return os.environ.get("NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://localhost:8000")
```

`_problem_details.py` loses `_PROBLEM_TYPE_BASE` and routes every type URI
through one helper:

```python
def _type_uri(code: ErrorCode | str) -> str:
    code_str = code.value if isinstance(code, ErrorCode) else code
    return f"{problem_docs_base_url()}/problems/{code_str}"
```

`tenant_resolution_error_to_problem_details` switches to
`_type_uri("tenant_not_resolved")` so all type URIs flow through the same
constructor.

`asgi.create_app()`:

* Mount `create_static_files_router(path="/problems",
  directories=[importlib.resources.files("novamoc.api") / "_problem_html"],
  html_mode=True, name="problems")`. With `html_mode=True`,
  `/problems/name_reserved` resolves to `name_reserved.html`.
* Extend the auth middleware exclude regex from `^/openapi` to
  `^/(openapi|problems)`. Docs are public.

## Test plan

`tests/api/test_problem_docs.py` (new):

* Session-scoped autouse fixture invokes `render_all()` so the package's
  `_problem_html` directory is populated before any test boots the app.
  Editing a markdown doc and re-running `pytest` works without remembering
  `just render-problem-docs`.
* `test_every_code_has_a_doc` — asserts `PROBLEM_CODES` matches the set of
  `docs/problems/*.md` stems. Catches drift without needing a built wheel.
* `test_problem_doc_endpoint_serves_html` — parametrize over `PROBLEM_CODES`,
  hit `GET /problems/<code>`, expect 200, `text/html`, body contains
  `_TITLES[code]`.
* `test_problem_type_uri_dereferences` — for one error path (`name_reserved`),
  trigger the error, parse the `type` URI from the problem-details body, GET
  that path, expect 200. Closes the loop the issue is about.
* `test_unknown_code_404s` — `GET /problems/does_not_exist` returns 404.

`tests/api/test_problem_details.py` (existing): assertions that hardcode
`urn:novamoc:problems:` switch to building the expected URI from the
env-driven base. A session fixture sets `NOVAMOC_PROBLEM_DOCS_BASE_URL` to a
stable value (e.g. `http://test`) so all tests share one expectation.

## Other touch points

* `.gitignore`: add `src/py/novamoc/api/_problem_html/`.
* `docs/adr/016-rfc9457-problem-details-error-envelope.md`: a small note in
  "More Information" that issue #13 is resolved and the URN placeholder is
  retired. The decision itself does not change.
* `CLAUDE.md`: no change required — the schema-endpoint and error-envelope
  prose stays accurate.

## Non-goals

* Building a docs site. The URL-base config knob exists so a future docs site
  can take over without changes here, but designing/deploying that site is
  out of scope.
* Hot reload of markdown in a long-running dev server. `just
  render-problem-docs` is fast (~7 small files) and re-runnable; running
  `just serve` after editing prose is acceptable for the lifetime of this
  endpoint.
* Frontmatter-driven metadata. Title and HTTP status remain in code so the
  wire contract is not parsed out of prose.

## Migration

* Existing tests asserting `urn:novamoc:problems:<code>` need a one-line
  update once the type URI is env-driven.
* No client SDKs exist; the wire change is invisible to anyone outside this
  repo.
