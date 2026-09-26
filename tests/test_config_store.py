"""Tests for boomarr.config_store (the web UI's view of boomarr.yml)."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

from boomarr.config import ConfigError, build_config
from boomarr.config_store import (
    SECRET_PREFIX,
    ConfigConflictError,
    ConfigReadOnlyError,
    ConfigStore,
    SecretMasker,
    config_to_file_data,
    serialize,
)

NO_LOG_FILE = {"logging": {"dir": ""}}


def _store(config_dir: Path) -> ConfigStore:
    return ConfigStore(config_dir, "boomarr.yml", NO_LOG_FILE)


def _read(config_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((config_dir / "boomarr.yml").read_text(encoding="utf-8"))


class TestSerialize:
    def test_omits_defaults_but_keeps_type(self, config_dir: Path) -> None:
        config = _store(config_dir).load()
        data = serialize(config)
        assert "probe_workers" not in data
        filters = data["libraries"][0]["symlink_libraries"][0]["filters"]
        assert filters == [{"type": "audio_language", "languages": ["deu"]}]

    def test_language_with_aliases_and_keep_defaults(self, config_dir: Path) -> None:
        config = build_config(
            {
                "libraries": [
                    {
                        "name": "x",
                        "input_path": str(config_dir / "in"),
                        "output_path": str(config_dir / "out"),
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {
                                        "type": "audio_language",
                                        "languages": [
                                            {"code": "deu", "aliases": ["gsw"]}
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
            config_dir,
            "boomarr.yml",
        )
        data = serialize(config)
        lang = data["libraries"][0]["symlink_libraries"][0]["filters"][0]["languages"]
        assert lang == [{"code": "deu", "aliases": ["gsw"]}]
        full = serialize(config, keep_defaults=True)
        assert full["probe_workers"] == 4
        assert full["libraries"][0]["symlink_libraries"][0]["filters"][0][
            "languages"
        ] == [{"code": "deu", "aliases": ["gsw"]}]

    def test_plain_values(self) -> None:
        assert serialize({"a": Path("/x"), "b": (1, 2)}) == {"a": "/x", "b": [1, 2]}


class TestConfigToFileData:
    def test_database_in_config_dir_is_omitted(self, config_dir: Path) -> None:
        config = _store(config_dir).load()
        assert "database" not in config_to_file_data(config, {})

    def test_defaults_only(self, config_dir: Path) -> None:
        config = build_config({}, config_dir, "boomarr.yml")
        assert config_to_file_data(config, {}) == {}

    def test_custom_database_file_name(self, config_dir: Path) -> None:
        raw = {"database": {"type": "sqlite", "file_name": "x.db"}}
        config = build_config(raw, config_dir, "boomarr.yml")
        assert config_to_file_data(config, raw)["database"] == {
            "type": "sqlite",
            "file_name": "x.db",
        }

    def test_database_elsewhere_is_kept(self, config_dir: Path, tmp_path: Path) -> None:
        raw = {"database": {"type": "sqlite", "dir": str(tmp_path / "db")}}
        config = build_config(raw, config_dir, "boomarr.yml")
        data = config_to_file_data(config, raw)
        assert data["database"] == {"type": "sqlite", "dir": str(tmp_path / "db")}

    def test_env_overrides_are_restored_from_file(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOMARR_API_KEY", "from-env")
        config = build_config({}, config_dir, "boomarr.yml")
        assert "server.api_key" in config._env_overrides
        assert "api_key" not in config_to_file_data(config, {}).get("server", {})
        raw = {"server": {"api_key": "file-key"}}
        config = build_config(raw, config_dir, "boomarr.yml")
        assert config_to_file_data(config, raw)["server"]["api_key"] == "file-key"


class TestSecretMasker:
    def test_mask_and_unmask(self, config_dir: Path) -> None:
        raw = {"server": {"api_key": "s3cret"}, "notifications": {"urls": ["json://x"]}}
        config = build_config(raw, config_dir, "boomarr.yml")
        masker = SecretMasker()
        masked = masker.mask(config)
        token = masked["server"]["api_key"]
        assert token.startswith(SECRET_PREFIX)
        assert "s3cret" not in str(masked)
        assert masker.token("s3cret") == token
        restored = masker.unmask({"a": [token, "plain"], "b": {"c": token}}, config)
        assert restored == {"a": ["s3cret", "plain"], "b": {"c": "s3cret"}}

    def test_unknown_token(self, config_dir: Path) -> None:
        config = build_config({}, config_dir, "boomarr.yml")
        with pytest.raises(ConfigError) as exc:
            SecretMasker().unmask({"x": [f"{SECRET_PREFIX}nope"]}, config)
        assert exc.value.errors[0]["loc"] == ["x", 0]

    def test_mask_plain_dict(self) -> None:
        assert SecretMasker().mask({"a": 1}) == {"a": 1}


class TestConfigStore:
    def test_document(self, config_dir: Path) -> None:
        store = _store(config_dir)
        doc = store.document()
        assert doc["writable"] is True
        assert doc["path"] == str(config_dir / "boomarr.yml")
        assert len(doc["etag"]) == 32
        assert "config_dir" not in doc["config"]
        assert doc["config"]["libraries"][0]["name"] == "Movies"

    def test_save_roundtrip_keeps_secrets_and_backup(self, config_dir: Path) -> None:
        path = config_dir / "boomarr.yml"
        path.write_text(
            path.read_text()
            + "media_servers:\n  - type: plex\n    url: http://plex\n    token: t0k\n"
        )
        os.chmod(path, 0o640)
        store = _store(config_dir)
        doc = store.document()
        assert doc["config"]["media_servers"][0]["token"].startswith(SECRET_PREFIX)
        doc["config"]["probe_workers"] = 7
        config = store.save(doc["config"], etag=doc["etag"])
        assert config.probe_workers == 7
        data = _read(config_dir)
        assert data["probe_workers"] == 7
        assert data["media_servers"][0] == {
            "type": "plex",
            "url": "http://plex",
            "token": "t0k",
        }
        assert (config_dir / "boomarr.yml.bak").exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        assert path.read_text().startswith("# Boomarr configuration")

    def test_save_conflict(self, config_dir: Path) -> None:
        store = _store(config_dir)
        doc = store.document()
        with pytest.raises(ConfigConflictError):
            store.save(doc["config"], etag="stale")

    def test_save_invalid(self, config_dir: Path) -> None:
        store = _store(config_dir)
        doc = store.document()
        doc["config"]["libraries"][0]["name"] = ""
        with pytest.raises(ConfigError) as exc:
            store.save(doc["config"])
        assert exc.value.errors[0]["loc"] == ["libraries", 0, "name"]
        with pytest.raises(ConfigError):
            store.validate([])  # ty: ignore[invalid-argument-type]

    def test_validate_strips_never_written_keys(self, config_dir: Path) -> None:
        store = _store(config_dir)
        doc = store.document()["config"]
        doc["config_dir"] = "/elsewhere"
        doc["logging"]["dir"] = "/elsewhere"
        config = store.validate(doc)
        assert config.config_dir == config_dir

    def test_validate_without_logging_section(self, config_dir: Path) -> None:
        store = _store(config_dir)
        doc = store.document()["config"]
        del doc["logging"]
        assert store.validate(doc).libraries[0].name == "Movies"

    def test_env_override_not_written(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOMARR_API_KEY", "env-key")
        store = _store(config_dir)
        doc = store.document()
        assert "server.api_key" in doc["env_overrides"]
        store.save(doc["config"])
        assert "server" not in _read(config_dir)

    def test_env_override_keeps_file_value(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = config_dir / "boomarr.yml"
        path.write_text(path.read_text() + "logging:\n  level: DEBUG\n")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        store = _store(config_dir)
        config = store.load()
        assert config.logging.level == "WARNING"
        store.save(store.document()["config"])
        assert _read(config_dir)["logging"]["level"] == "DEBUG"

    def test_unmask_fragment(self, config_dir: Path) -> None:
        path = config_dir / "boomarr.yml"
        path.write_text(path.read_text() + "server:\n  api_key: k3y\n")
        store = _store(config_dir)
        token = store.document()["config"]["server"]["api_key"]
        assert store.unmask({"api_key": token}) == {"api_key": "k3y"}

    def test_read_only(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _store(config_dir)
        monkeypatch.setattr(os, "access", lambda *_: False)
        assert store.writable is False
        with pytest.raises(ConfigReadOnlyError):
            store.save(store.document()["config"])

    def test_writable_missing_file(self, tmp_path: Path) -> None:
        store = ConfigStore(tmp_path, "new.yml", NO_LOG_FILE)
        assert store.writable is True
        assert store.etag == store.etag
        store.path.unlink(missing_ok=True)
        assert len(store.etag) == 32

    def test_export_import(self, config_dir: Path) -> None:
        store = _store(config_dir)
        text = store.export_yaml()
        config = store.import_yaml(text.replace("name: Movies", "name: Films"))
        assert config.libraries[0].name == "Films"

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("a: [", "not valid YAML"),
            ("- 1\n", "must be a mapping"),
            ("libraries: 3\n", None),
        ],
    )
    def test_import_invalid(
        self, config_dir: Path, text: str, message: str | None
    ) -> None:
        store = _store(config_dir)
        with pytest.raises(ConfigError, match=message):
            store.import_yaml(text)
        assert "Movies" in store.export_yaml()

    def test_import_empty_file_is_valid(self, config_dir: Path) -> None:
        config = _store(config_dir).import_yaml("")
        assert config.libraries == []

    def test_write_failure_cleans_up(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(config_dir)

        def boom(*_: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            store.import_yaml("probe_workers: 2\n")
        assert [
            p.name for p in config_dir.iterdir() if p.name.startswith(".boomarr")
        ] == []

    def test_first_write_creates_private_file(self, tmp_path: Path) -> None:
        store = ConfigStore(tmp_path / "fresh", "boomarr.yml", NO_LOG_FILE)
        store.path.parent.mkdir()
        store.import_yaml("probe_workers: 3\n")
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
