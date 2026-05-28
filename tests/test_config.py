from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from novamoc.config import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    Settings,
    _bool_env,
    _float_env,
    _int_env,
    _str_env,
)

_AUTH_ENV_VARS = (
    "NOVAMOC_AUTH_SESSION_TTL_SECONDS",
    "NOVAMOC_AUTH_SESSION_COOKIE_NAME",
    "NOVAMOC_AUTH_SESSION_COOKIE_SECURE",
    "NOVAMOC_AUTH_ARGON2_TIME_COST",
    "NOVAMOC_AUTH_ARGON2_MEMORY_COST_KIB",
    "NOVAMOC_AUTH_ARGON2_PARALLELISM",
)


class TestStrEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_STR", raising=False)
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "fallback"

    def test_returns_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_STR", "from-env")
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "from-env"

    def test_factory_re_reads_each_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_STR", raising=False)
        factory = _str_env("NOVAMOC_X_TEST_STR", "fallback")
        assert factory() == "fallback"
        monkeypatch.setenv("NOVAMOC_X_TEST_STR", "now-set")
        assert factory() == "now-set"


class TestBoolEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_BOOL", raising=False)
        assert _bool_env("NOVAMOC_X_TEST_BOOL", True)() is True
        assert _bool_env("NOVAMOC_X_TEST_BOOL", False)() is False

    def test_parses_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "true")
        assert _bool_env("NOVAMOC_X_TEST_BOOL", False)() is True
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "false")
        assert _bool_env("NOVAMOC_X_TEST_BOOL", True)() is False

    def test_garbage_propagates_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_BOOL", "yes")
        with pytest.raises(ValueError, match="cannot parse"):
            _bool_env("NOVAMOC_X_TEST_BOOL", False)()


class TestFloatEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_FLOAT", raising=False)
        assert _float_env("NOVAMOC_X_TEST_FLOAT", 2.5)() == 2.5

    def test_parses_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_FLOAT", "0.125")
        assert _float_env("NOVAMOC_X_TEST_FLOAT", 1.0)() == 0.125

    def test_garbage_propagates_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_FLOAT", "not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            _float_env("NOVAMOC_X_TEST_FLOAT", 1.0)()


class TestIntEnv:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOVAMOC_X_TEST_INT", raising=False)
        assert _int_env("NOVAMOC_X_TEST_INT", 7)() == 7

    def test_parses_env_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_INT", "42")
        assert _int_env("NOVAMOC_X_TEST_INT", 0)() == 42

    def test_garbage_propagates_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_X_TEST_INT", "not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            _int_env("NOVAMOC_X_TEST_INT", 0)()


class TestDatabaseSettings:
    def test_busy_timeout_defaults_to_five_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_DB_BUSY_TIMEOUT_SECONDS", raising=False)
        assert DatabaseSettings().busy_timeout_seconds == 5.0

    def test_env_overrides_busy_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_DB_BUSY_TIMEOUT_SECONDS", "2.5")
        assert DatabaseSettings().busy_timeout_seconds == 2.5

    def test_garbage_busy_timeout_propagates_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_DB_BUSY_TIMEOUT_SECONDS", "not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            DatabaseSettings()


class TestAppSettings:
    def test_default_hlc_drift_is_one_minute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", raising=False)
        assert AppSettings().hlc_drift_limit_seconds == 60.0

    def test_env_overrides_drift_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", "12.5")
        assert AppSettings().hlc_drift_limit_seconds == 12.5

    def test_schema_changes_max_batch_size_defaults_to_500(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", raising=False)
        assert AppSettings().schema_changes_max_batch_size == 500

    def test_env_overrides_schema_changes_max_batch_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", "42")
        assert AppSettings().schema_changes_max_batch_size == 42

    def test_garbage_schema_changes_max_batch_size_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_SCHEMA_CHANGES_MAX_BATCH_SIZE", "not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            AppSettings()


class TestAuthSettings:
    def test_defaults_are_production_safe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in _AUTH_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        s = AuthSettings()
        assert s.session_ttl_seconds == 86400
        assert s.session_cookie_name == "novamoc_session"
        # Production-safe default: Secure cookies (HTTPS-only). Local
        # dev opts out via NOVAMOC_AUTH_SESSION_COOKIE_SECURE=false.
        assert s.session_cookie_secure is True
        assert s.argon2_time_cost == 3
        assert s.argon2_memory_cost_kib == 65536
        assert s.argon2_parallelism == 4

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_AUTH_SESSION_TTL_SECONDS", "3600")
        monkeypatch.setenv("NOVAMOC_AUTH_SESSION_COOKIE_NAME", "sid")
        monkeypatch.setenv("NOVAMOC_AUTH_SESSION_COOKIE_SECURE", "false")
        monkeypatch.setenv("NOVAMOC_AUTH_ARGON2_TIME_COST", "5")
        monkeypatch.setenv("NOVAMOC_AUTH_ARGON2_MEMORY_COST_KIB", "131072")
        monkeypatch.setenv("NOVAMOC_AUTH_ARGON2_PARALLELISM", "8")
        s = AuthSettings()
        assert s.session_ttl_seconds == 3600
        assert s.session_cookie_name == "sid"
        assert s.session_cookie_secure is False
        assert s.argon2_time_cost == 5
        assert s.argon2_memory_cost_kib == 131072
        assert s.argon2_parallelism == 8


class TestSettings:
    def test_default_construction_uses_env_aware_children(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "sqlite+aiosqlite:///x.sqlite")
        monkeypatch.setenv("NOVAMOC_SERVER_GRANIAN", "false")
        monkeypatch.setenv("NOVAMOC_PROBLEM_DOCS_BASE_URL", "https://x")
        monkeypatch.setenv("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", "30")

        s = Settings()
        assert s.db.url == "sqlite+aiosqlite:///x.sqlite"
        assert s.server.granian is False
        assert s.app.docs_base_url == "https://x"
        assert s.app.hlc_drift_limit_seconds == 30.0

    def test_explicit_child_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_DB_URL", "from-env")
        s = Settings(db=DatabaseSettings(url="explicit"))
        assert s.db.url == "explicit"

    def test_is_frozen(self) -> None:
        s = Settings()
        with pytest.raises(FrozenInstanceError):
            s.db = DatabaseSettings()  # ty: ignore[invalid-assignment]
