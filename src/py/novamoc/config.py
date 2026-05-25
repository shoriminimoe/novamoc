"""Application-level configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})


def _to_bool(value: str | None, *, default: bool) -> bool:
    """Parse a bool from an env-var string; ``None`` returns ``default``.

    Accepts ``true`` / ``false`` / ``1`` / ``0`` case-insensitively. Any
    other value raises ``ValueError`` so a typo in the deployment is a
    startup failure, not a silent default.
    """
    if value is None:
        return default
    normalized = value.lower()
    if normalized in _TRUE_LITERALS:
        return True
    if normalized in _FALSE_LITERALS:
        return False
    msg = f"cannot parse {value!r} as bool; expected one of true/false/1/0"
    raise ValueError(msg)


def _str_env(name: str, default: str) -> Callable[[], str]:
    """Build a ``default_factory`` that reads ``name`` from env at call time."""
    return lambda: os.environ.get(name, default)


def _bool_env(name: str, default: bool) -> Callable[[], bool]:
    """Build a ``default_factory`` that reads ``name`` from env and parses as bool."""
    return lambda: _to_bool(os.environ.get(name), default=default)


def _float_env(name: str, default: float) -> Callable[[], float]:
    """Build a ``default_factory`` that reads ``name`` from env and parses as float.

    A non-numeric value raises ``ValueError`` at startup rather than
    silently falling through to the default.
    """

    def _read() -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            msg = f"cannot parse {raw!r} as float for {name}"
            raise ValueError(msg) from exc

    return _read


def _int_env(name: str, default: int) -> Callable[[], int]:
    """Build a ``default_factory`` that reads ``name`` from env and parses as int.

    A non-integer value raises ``ValueError`` at startup rather than
    silently falling through to the default.
    """

    def _read() -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            msg = f"cannot parse {raw!r} as int for {name}"
            raise ValueError(msg) from exc

    return _read


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = field(
        default_factory=_str_env("NOVAMOC_DB_URL", "sqlite+aiosqlite:///novamoc.sqlite")
    )
    static_pool: bool = field(
        default_factory=_bool_env("NOVAMOC_DB_STATIC_POOL", False)
    )
    create_all: bool = field(default_factory=_bool_env("NOVAMOC_DB_CREATE_ALL", True))
    before_send_handler: str = field(
        default_factory=_str_env("NOVAMOC_DB_BEFORE_SEND_HANDLER", "autocommit")
    )


@dataclass(frozen=True, slots=True)
class ServerSettings:
    granian: bool = field(default_factory=_bool_env("NOVAMOC_SERVER_GRANIAN", True))


EVENT_CATCHUP_DEFAULT_BATCH_SIZE = 500
EVENT_CATCHUP_MAX_BATCH_SIZE = 5000

SNAPSHOT_DEFAULT_BATCH_SIZE = 1000
SNAPSHOT_MAX_BATCH_SIZE = 5000


@dataclass(frozen=True, slots=True)
class AppSettings:
    """App-wide tunables that don't belong to a single subsystem.

    Attributes:
        docs_base_url: Base URL the problem-details ``type`` URIs
            point at (the static-files router under ``/problems``
            is served from the same host).
        hlc_drift_limit_seconds: One-sided clock-drift budget
            (ADR-006). Events whose HLC physical component sits
            more than this many seconds ahead of the server wall
            clock are rejected at acceptance time.
        schema_changes_max_batch_size: Upper bound on rows returned
            by a single ``GET /schema/changes`` page (M2.2). Clients
            page via ``next_since`` / ``has_more``.
    """

    docs_base_url: str = field(
        default_factory=_str_env(
            "NOVAMOC_PROBLEM_DOCS_BASE_URL", "http://localhost:8000"
        )
    )
    hlc_drift_limit_seconds: float = field(
        default_factory=_float_env("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", 60.0)
    )
    schema_changes_max_batch_size: int = field(
        default_factory=_int_env("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", 500)
    )


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Authentication subsystem tunables (ADR-020).

    Defaults are the production-safe values throughout: dev relaxes
    them via env vars rather than the other way around.

    Attributes:
        session_ttl_seconds: Absolute lifetime of a session cookie,
            in seconds (24h).
        session_cookie_name: Name of the cookie carrying the session id.
        session_cookie_secure: ``Secure`` flag on the session cookie.
            Defaults to ``True`` (HTTPS-only); local development over
            loopback opts out with
            ``NOVAMOC_AUTH_SESSION_COOKIE_SECURE=false``.
        argon2_time_cost: argon2id ``t`` parameter (iterations) —
            OWASP "Argon2id" recommendation rounded up.
        argon2_memory_cost_kib: argon2id ``m`` parameter (memory, KiB)
            — 64 MiB, OWASP minimum for the (t=3, p=4) profile.
        argon2_parallelism: argon2id ``p`` parameter.
    """

    session_ttl_seconds: int = field(
        default_factory=_int_env("NOVAMOC_AUTH_SESSION_TTL_SECONDS", 86400)
    )
    session_cookie_name: str = field(
        default_factory=_str_env("NOVAMOC_AUTH_SESSION_COOKIE_NAME", "novamoc_session")
    )
    session_cookie_secure: bool = field(
        default_factory=_bool_env("NOVAMOC_AUTH_SESSION_COOKIE_SECURE", True)
    )
    argon2_time_cost: int = field(
        default_factory=_int_env("NOVAMOC_AUTH_ARGON2_TIME_COST", 3)
    )
    argon2_memory_cost_kib: int = field(
        default_factory=_int_env("NOVAMOC_AUTH_ARGON2_MEMORY_COST_KIB", 65536)
    )
    argon2_parallelism: int = field(
        default_factory=_int_env("NOVAMOC_AUTH_ARGON2_PARALLELISM", 4)
    )


@dataclass(frozen=True, slots=True)
class Settings:
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    app: AppSettings = field(default_factory=AppSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)


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
