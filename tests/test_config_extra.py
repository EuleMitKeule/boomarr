"""Edge cases of boomarr.config not covered elsewhere."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from boomarr.config import (
    AudioLanguageFilterConfig,
    Config,
    ConfigError,
    OIDCConfig,
    ResolutionFilterConfig,
    ServerConfig,
    _short,
    build_config,
    clean_loc,
    clean_msg,
)


def _library(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "name": "Movies",
        "input_path": str(tmp_path / "in"),
        "symlink_libraries": [
            {"filters": [{"type": "audio_language", "languages": ["deu"]}]}
        ],
        **extra,
    }


class TestFilters:
    def test_explicit_suffix(self) -> None:
        cfg = AudioLanguageFilterConfig(languages=["deu"], suffix="german", invert=True)
        assert cfg.effective_suffix() == "german"

    def test_languages_must_be_a_list(self) -> None:
        with pytest.raises(ValidationError):
            AudioLanguageFilterConfig(languages="deu")

    def test_invalid_height(self) -> None:
        with pytest.raises(ValidationError):
            ResolutionFilterConfig(min_height="big")

    def test_short_generic_dict(self) -> None:
        assert _short({"a": 1, "b": [2]}) == "{a=1, b=[2]}"


class TestServerAndOidc:
    def test_invalid_trusted_proxy(self) -> None:
        with pytest.raises(ValidationError, match="not an IP address"):
            ServerConfig(trusted_proxies=["proxy.local"])

    def test_trusted_proxies_are_stripped(self) -> None:
        assert ServerConfig(trusted_proxies=[" 10.0.0.0/8 "]).trusted_proxies == [
            "10.0.0.0/8"
        ]

    def test_oidc_validation(self) -> None:
        with pytest.raises(ValidationError, match="http"):
            OIDCConfig(issuer="id.example.com")
        with pytest.raises(ValidationError, match="needs 'issuer'"):
            OIDCConfig(enabled=True)
        assert OIDCConfig(issuer="  ").issuer is None
        cfg = OIDCConfig(issuer="https://id.example.com/", scopes=["email"])
        assert cfg.scopes == ["openid", "email"]
        assert (
            cfg.discovery_url
            == "https://id.example.com/.well-known/openid-configuration"
        )
        full = "https://id.example.com/.well-known/openid-configuration"
        assert OIDCConfig(issuer=full).discovery_url == full


class TestConfigModel:
    def test_relative_output_path_is_resolved(self, tmp_path: Path) -> None:
        cfg = build_config({"output_path": "out"}, tmp_path, "boomarr.yml")
        assert cfg.output_path is not None and cfg.output_path.is_absolute()

    def test_multiple_webhook_triggers(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Only one webhook"):
            build_config(
                {"triggers": [{"type": "webhook"}, {"type": "webhook", "port": 1234}]},
                tmp_path,
                "boomarr.yml",
            )

    def test_webhook_migration_keeps_custom_server(self, tmp_path: Path) -> None:
        cfg = build_config(
            {"triggers": [{"type": "webhook", "port": 1111}], "server": {"port": 2222}},
            tmp_path,
            "boomarr.yml",
        )
        assert cfg.server.port == 2222
        assert any("deprecated" in w for w in cfg.warnings)

    def test_missing_output_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="missing output_path"):
            build_config({"libraries": [_library(tmp_path)]}, tmp_path, "boomarr.yml")

    def test_notify_urls_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOMARR_NOTIFY_URLS", "json://a")
        cfg = build_config({}, tmp_path, "boomarr.yml")
        assert "notifications.urls" in cfg._env_overrides

    def test_database_must_be_mapping(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="'database' must be a mapping"):
            build_config({"database": "sqlite"}, tmp_path, "boomarr.yml")

    def test_model_is_config(self, tmp_path: Path) -> None:
        assert isinstance(build_config({}, tmp_path, "boomarr.yml"), Config)


class TestErrorCleanup:
    def test_clean_loc(self) -> None:
        data = {"probers": [{"type": "sonarr"}], "x": 1}
        assert clean_loc(("probers", 0, "sonarr", "url"), data) == ["probers", 0, "url"]
        assert clean_loc(("probers", 5, "url"), data) == ["probers", 5, "url"]
        assert clean_loc(("x", "y", "z"), data) == ["x", "y", "z"]

    def test_clean_msg(self) -> None:
        assert clean_msg("Value error, bad thing") == "Bad thing"
        assert clean_msg("Assertion failed, nope") == "Nope"
        assert clean_msg("") == ""
