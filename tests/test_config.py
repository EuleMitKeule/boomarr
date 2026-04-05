"""Tests for boomarr.config."""

import textwrap
from pathlib import Path

import pytest

from boomarr.config import (
    Config,
    LoggingConfig,
    get_config,
    load_config,
)
from boomarr.const import (
    DEFAULT_LOG_COLOR,
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    LogLevel,
)

# ---------------------------------------------------------------------------
# LoggingConfig
# ---------------------------------------------------------------------------


class TestLoggingConfig:
    def test_defaults(self) -> None:
        cfg = LoggingConfig()
        assert cfg.level == DEFAULT_LOG_LEVEL
        assert cfg.format == DEFAULT_LOG_FORMAT
        assert cfg.date_format == DEFAULT_LOG_DATE_FORMAT
        assert cfg.dir == DEFAULT_LOG_DIR
        assert cfg.file_name == DEFAULT_LOG_FILE_NAME
        assert cfg.color == DEFAULT_LOG_COLOR

    def test_log_file_combined(self) -> None:
        cfg = LoggingConfig(dir=Path("/logs"), file_name="app.log")
        assert cfg.log_file == Path("/logs/app.log")

    def test_log_file_none_when_dir_is_none(self) -> None:
        cfg = LoggingConfig(dir=None, file_name="app.log")
        assert cfg.log_file is None

    def test_log_file_none_when_file_name_is_none(self) -> None:
        cfg = LoggingConfig(dir=Path("/logs"), file_name=None)
        assert cfg.log_file is None

    def test_level_coercion_lowercase(self) -> None:
        cfg = LoggingConfig(level="debug")  # type: ignore[arg-type]
        assert cfg.level == LogLevel.DEBUG

    def test_level_coercion_mixed_case(self) -> None:
        cfg = LoggingConfig(level="Warning")  # type: ignore[arg-type]
        assert cfg.level == LogLevel.WARNING

    def test_empty_string_dir_becomes_none(self) -> None:
        cfg = LoggingConfig(dir="")  # type: ignore[arg-type]
        assert cfg.dir is None

    def test_whitespace_string_dir_becomes_none(self) -> None:
        cfg = LoggingConfig(dir="   ")  # type: ignore[arg-type]
        assert cfg.dir is None

    def test_empty_string_file_name_becomes_none(self) -> None:
        cfg = LoggingConfig(file_name="")
        assert cfg.file_name is None

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(Exception):
            LoggingConfig(level="NOTREAL")  # type: ignore[arg-type]

    def test_level_coercion_when_already_enum(self) -> None:
        """Test that passing non-string value (e.g., already-converted LogLevel) passes through."""
        cfg = LoggingConfig(level=LogLevel.ERROR)
        assert cfg.level == LogLevel.ERROR

    def test_level_non_string_passthrough(self) -> None:
        """Test that non-string values pass through the validator unchanged."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoggingConfig(level=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_raises_before_load(self) -> None:
        with pytest.raises(RuntimeError, match="load_config"):
            get_config()

    def test_returns_config_after_load(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml")
        assert get_config() is cfg


# ---------------------------------------------------------------------------
# load_config – config file creation
# ---------------------------------------------------------------------------


class TestLoadConfigFileCreation:
    def test_creates_config_file_when_missing(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yml"
        assert not config_path.exists()
        load_config(tmp_path, "config.yml")
        assert config_path.exists()

    def test_created_file_is_valid_yaml(self, tmp_path: Path) -> None:
        import yaml

        load_config(tmp_path, "config.yml")
        with (tmp_path / "config.yml").open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "logging" in data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        load_config(nested, "config.yml")
        assert (nested / "config.yml").exists()

    def test_does_not_overwrite_existing_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            textwrap.dedent("""\
                logging:
                  level: DEBUG
            """),
            encoding="utf-8",
        )
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.level == LogLevel.DEBUG


# ---------------------------------------------------------------------------
# load_config – value resolution priority
# ---------------------------------------------------------------------------


class TestLoadConfigPriority:
    """Env var > CLI arg > yaml file > default (highest to lowest)."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def test_yaml_overrides_default(self, tmp_path: Path) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              level: ERROR
            """,
        )
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.level == LogLevel.ERROR

    def test_cli_overrides_yaml(self, tmp_path: Path) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              level: ERROR
            """,
        )
        cfg = load_config(tmp_path, "config.yml", log_level=LogLevel.DEBUG)
        assert cfg.logging.level == LogLevel.DEBUG

    def test_env_var_overrides_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              level: ERROR
            """,
        )
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.level == LogLevel.WARNING

    def test_cli_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_yaml(tmp_path / "config.yml", "")
        monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
        cfg = load_config(tmp_path, "config.yml", log_level=LogLevel.DEBUG)
        assert cfg.logging.level == LogLevel.DEBUG

    def test_cli_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "mylogs"
        cfg = load_config(tmp_path, "config.yml", log_dir=log_dir)
        assert cfg.logging.dir == log_dir

    def test_cli_log_file_name(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml", log_file_name="custom.log")
        assert cfg.logging.file_name == "custom.log"

    def test_env_var_log_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log_dir = tmp_path / "envlogs"
        monkeypatch.setenv("LOG_DIR", str(log_dir))
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.dir == log_dir

    def test_env_var_log_file_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_FILE_NAME", "env.log")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.file_name == "env.log"


# ---------------------------------------------------------------------------
# load_config – Config fields
# ---------------------------------------------------------------------------


class TestLoadConfigFields:
    def test_config_dir_stored(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.config_dir == tmp_path

    def test_config_file_stored(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "my.yml")
        assert cfg.config_file == "my.yml"

    def test_returns_config_instance(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml")
        assert isinstance(cfg, Config)

    def test_singleton_replaced_on_second_call(self, tmp_path: Path) -> None:
        cfg1 = load_config(tmp_path, "config.yml")
        cfg2 = load_config(tmp_path, "config.yml")
        assert cfg1 is not cfg2


# ---------------------------------------------------------------------------
# _to_yaml_serializable
# ---------------------------------------------------------------------------


class TestToYamlSerializable:
    """Test the _to_yaml_serializable helper function."""

    def test_scalar_passthrough(self) -> None:
        """Scalar values should pass through unchanged."""
        from boomarr.config import _to_yaml_serializable

        assert _to_yaml_serializable("hello") == "hello"
        assert _to_yaml_serializable(42) == 42
        assert _to_yaml_serializable(3.14) == 3.14
        assert _to_yaml_serializable(True) is True
        assert _to_yaml_serializable(None) is None

    def test_enum_conversion(self) -> None:
        """Enums should be converted to their values."""
        from boomarr.config import _to_yaml_serializable

        result = _to_yaml_serializable(LogLevel.WARNING)
        assert result == "WARNING"

    def test_path_conversion(self) -> None:
        """Path objects should be converted to strings."""
        from boomarr.config import _to_yaml_serializable

        test_path = Path("/some/path")
        result = _to_yaml_serializable(test_path)
        assert result == str(test_path)
        assert isinstance(result, str)

    def test_dict_recursive(self) -> None:
        """Dicts should be recursively processed."""
        from boomarr.config import _to_yaml_serializable

        test_path = Path("/logs")
        result = _to_yaml_serializable(
            {
                "level": LogLevel.DEBUG,
                "dir": test_path,
                "nested": {"value": "test"},
            }
        )
        assert result == {
            "level": "DEBUG",
            "dir": str(test_path),
            "nested": {"value": "test"},
        }

    def test_list_recursive(self) -> None:
        """Lists should be recursively processed."""
        from boomarr.config import _to_yaml_serializable

        test_path = Path("/data")
        result = _to_yaml_serializable(
            [
                LogLevel.INFO,
                test_path,
                123,
            ]
        )
        assert result == ["INFO", str(test_path), 123]

    def test_tuple_recursive(self) -> None:
        """Tuples should be recursively processed and become lists."""
        from boomarr.config import _to_yaml_serializable

        test_path = Path("/etc")
        result = _to_yaml_serializable((LogLevel.CRITICAL, test_path))
        assert result == ["CRITICAL", str(test_path)]


# ---------------------------------------------------------------------------
# load_config – validation errors
# ---------------------------------------------------------------------------


class TestLoadConfigValidationError:
    """Test ValidationError handling in load_config."""

    def test_invalid_config_exits(self, tmp_path: Path) -> None:
        """Test that invalid config file causes sys.exit(1)."""
        import yaml

        config_path = tmp_path / "config.yml"
        # Write invalid config (integer instead of string for a string field)
        config_path.write_text(
            yaml.safe_dump({"logging": {"format": 12345}}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            load_config(tmp_path, "config.yml")
        assert exc_info.value.code == 1
