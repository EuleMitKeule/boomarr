"""Tests for boomarr.health."""

import os
from pathlib import Path
from typing import Any

import pytest

from boomarr import health
from boomarr.config import Config, build_config
from boomarr.config_store import ConfigStore


def _config(config_dir: Path, **extra: Any) -> Config:
    store = ConfigStore(config_dir, "boomarr.yml", {"logging": {"dir": ""}})
    config = store.load()
    if extra:
        data = store.document()["config"]
        data.update(extra)
        config = store.validate(data)
    return config


def _checks(config: Config, **kwargs: Any) -> list[dict[str, Any]]:
    defaults: dict[str, Any] = {
        "config_writable": True,
        "has_credentials": True,
        "skip_readonly_check": True,
        "restart_required": False,
        "last_scan": None,
    }
    return health.run_checks(config, **{**defaults, **kwargs})


def _ids(checks: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in checks]


class TestPreflight:
    def test_no_libraries(self, tmp_path: Path) -> None:
        config = build_config({}, tmp_path, "boomarr.yml")
        assert (
            health.preflight(config, skip_readonly_check=False)
            == "No libraries configured"
        )

    def test_writable_source(self, config_dir: Path) -> None:
        config = _config(config_dir)
        reason = health.preflight(config, skip_readonly_check=False)
        assert reason is not None and "Movies" in reason
        assert health.preflight(config, skip_readonly_check=True) is None

    def test_missing_ffprobe(self, config_dir: Path) -> None:
        config = _config(
            config_dir, probers=[{"type": "ffprobe", "path": "no-such-ffprobe"}]
        )
        assert health.preflight(config, skip_readonly_check=True) == (
            "FFprobe not found: no-such-ffprobe"
        )

    def test_library_prober_override(self, config_dir: Path) -> None:
        config = _config(config_dir)
        data = ConfigStore(config_dir, "boomarr.yml").document()["config"]
        data["libraries"][0]["probers"] = [{"type": "ffprobe", "path": "other-ffprobe"}]
        config = ConfigStore(config_dir, "boomarr.yml").validate(data)
        assert health.missing_ffprobe(config) == ["other-ffprobe"]


class TestRunChecks:
    def test_healthy(self, config_dir: Path) -> None:
        checks = _checks(_config(config_dir))
        assert _ids(checks) == ["library:Movies:readonly"]
        assert checks[0]["level"] == "warning"

    def test_readonly_error_when_check_enabled(self, config_dir: Path) -> None:
        checks = _checks(_config(config_dir), skip_readonly_check=False)
        assert checks[0]["level"] == "error"

    def test_no_libraries(self, tmp_path: Path) -> None:
        checks = _checks(build_config({}, tmp_path, "boomarr.yml"))
        assert "libraries" in _ids(checks)

    def test_missing_source(self, config_dir: Path, movies_dir: Path) -> None:
        config = _config(config_dir)
        for path in sorted(movies_dir.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        movies_dir.rmdir()
        checks = _checks(config)
        assert checks[0]["id"] == "library:Movies"
        assert "does not exist" in checks[0]["message"]

    def test_permissions(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config(config_dir)
        monkeypatch.setattr(os, "access", lambda *_: False)
        ids = _ids(_checks(config, config_writable=False))
        assert {"library:Movies", "library:Movies:output", "config", "database"} <= set(
            ids
        )
        assert "library:Movies:readonly" not in ids

    def test_auth_none(self, config_dir: Path) -> None:
        config = _config(config_dir, auth={"method": "none"})
        assert "auth" in _ids(_checks(config))

    def test_auth_external_without_proxies(self, config_dir: Path) -> None:
        config = _config(config_dir, auth={"method": "external"})
        check = next(c for c in _checks(config) if c["id"] == "auth")
        assert check["level"] == "error"
        config = _config(
            config_dir,
            auth={"method": "external"},
            server={"trusted_proxies": ["10.0.0.0/8"]},
        )
        assert "auth" not in _ids(_checks(config))

    def test_auth_forms_without_account(self, config_dir: Path) -> None:
        assert "auth" in _ids(_checks(_config(config_dir), has_credentials=False))

    def test_memory_database_and_ffprobe(self, config_dir: Path) -> None:
        config = _config(
            config_dir,
            database={"type": "memory"},
            probers=[{"type": "ffprobe", "path": "missing-ffprobe"}],
        )
        checks = _checks(config)
        assert "ffprobe" in _ids(checks)
        assert "database" not in _ids(checks)

    @pytest.mark.parametrize(
        ("last_scan", "level", "text"),
        [
            ({"error": "boom"}, "error", "failed: boom"),
            ({"result": {"blocked": 1}}, "warning", "removal guard"),
            ({"result": {"errors": 2}}, "warning", "2 error(s)"),
            ({"result": {"errors": 0}}, None, None),
        ],
    )
    def test_last_scan(
        self,
        config_dir: Path,
        last_scan: dict[str, Any],
        level: str | None,
        text: str | None,
    ) -> None:
        checks = [
            c
            for c in _checks(_config(config_dir), last_scan=last_scan)
            if c["id"] == "scan"
        ]
        if level is None:
            assert checks == []
        else:
            assert checks[0]["level"] == level
            assert text in checks[0]["message"]

    def test_restart_and_sorting(self, config_dir: Path) -> None:
        checks = _checks(
            _config(config_dir), restart_required=True, last_scan={"error": "x"}
        )
        assert [c["level"] for c in checks] == ["error", "warning", "warning"]
        assert "restart" in _ids(checks)

    def test_unreadable_source(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config(config_dir)
        real = os.access

        def access(path: object, mode: int, *args: object, **kwargs: object) -> bool:
            if mode == os.R_OK | os.X_OK:
                return False
            return real(path, mode)  # ty: ignore[invalid-argument-type]

        monkeypatch.setattr(os, "access", access)
        messages = [c["message"] for c in _checks(config)]
        assert any("not readable" in m for m in messages)
