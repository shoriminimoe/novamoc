from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from novamoc.config import (
    AppSettings,
    DatabaseSettings,
    Settings,
    _bool_env,
    _float_env,
    _str_env,
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


class TestAppSettings:
    def test_default_hlc_drift_is_one_minute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", raising=False)
        assert AppSettings().hlc_drift_limit_seconds == 60.0

    def test_env_overrides_drift_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOVAMOC_HLC_DRIFT_LIMIT_SECONDS", "12.5")
        assert AppSettings().hlc_drift_limit_seconds == 12.5


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
