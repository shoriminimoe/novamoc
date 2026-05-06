"""Application-level configuration helpers.

Pre-auth dev configuration that previously lived here (the
``KNOWN_TENANT_IDS`` stub) was retired by ADR-017 — the tenant identity
now comes from the request envelope (Bearer token → ``RequestAuth``)
resolved by ``AuthenticationMiddleware``.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

_PROBLEM_DOCS_BASE_URL_ENV = "NOVAMOC_PROBLEM_DOCS_BASE_URL"
_PROBLEM_DOCS_BASE_URL_DEFAULT = "http://localhost:8000"


def problem_docs_base_url() -> str:
    return os.environ.get(_PROBLEM_DOCS_BASE_URL_ENV, _PROBLEM_DOCS_BASE_URL_DEFAULT)


def problem_html_dir() -> Path:
    """Return the directory holding rendered problem-details HTML.

    In a wheel install, uv_build's ``data = { purelib = "build/wheel_data" }``
    config installs the rendered HTML at ``<site-packages>/novamoc/html/``,
    so ``importlib.resources.files("novamoc") / "html"`` resolves it.

    In an editable install the wheel data is not materialized, so we fall
    back to the build-artifact tree at
    ``<repo-root>/build/wheel_data/novamoc/html/`` (populated by
    ``just render-problem-docs``).
    """
    pkg_dir = Path(str(files("novamoc")))
    primary = pkg_dir / "html"
    if primary.is_dir():
        return primary
    return pkg_dir.parents[2] / "build" / "wheel_data" / "novamoc" / "html"
