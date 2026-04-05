"""Tests for boomarr.config."""

import logging
import textwrap
from pathlib import Path

import pytest

from boomarr.config import (
    Config,
    GeneralConfig,
    LoggingConfig,
    LogRotationConfig,
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
    DEFAULT_LOG_ROTATION_BACKUP_COUNT,
    DEFAULT_LOG_ROTATION_ENABLED,
    DEFAULT_LOG_ROTATION_MAX_BYTES,
    DEFAULT_LOG_ROTATION_ROTATE_ON_START,
    DEFAULT_PGID,
    DEFAULT_PUID,
    DEFAULT_TZ,
    DEFAULT_UMASK,
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
        assert cfg.dir == DEFAULT_LOG_DIR.resolve()
        assert cfg.file_name == DEFAULT_LOG_FILE_NAME
        assert cfg.color == DEFAULT_LOG_COLOR

    def test_log_file_combined(self, tmp_path: Path) -> None:
        cfg = LoggingConfig(dir=tmp_path, file_name="app.log")
        assert cfg.log_file == tmp_path / "app.log"

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
# GeneralConfig
# ---------------------------------------------------------------------------


class TestGeneralConfig:
    def test_defaults(self) -> None:
        cfg = GeneralConfig()
        assert cfg.tz == DEFAULT_TZ
        assert cfg.puid == DEFAULT_PUID
        assert cfg.pgid == DEFAULT_PGID
        assert cfg.umask == DEFAULT_UMASK

    def test_valid_timezone(self) -> None:
        cfg = GeneralConfig(tz="America/New_York")
        assert cfg.tz == "America/New_York"

    def test_invalid_timezone_raises(self) -> None:
        with pytest.raises(Exception):
            GeneralConfig(tz="Not/A_Timezone")

    def test_empty_string_tz_becomes_default(self) -> None:
        cfg = GeneralConfig(tz="")
        assert cfg.tz == DEFAULT_TZ

    def test_whitespace_string_tz_becomes_default(self) -> None:
        cfg = GeneralConfig(tz="   ")
        assert cfg.tz == DEFAULT_TZ

    def test_tz_non_string_passthrough(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GeneralConfig(tz=123)  # type: ignore[arg-type]

    def test_valid_umask(self) -> None:
        cfg = GeneralConfig(umask="077")
        assert cfg.umask == "077"

    def test_umask_int_coercion(self) -> None:
        """YAML parses unquoted 022 as int 22; should be zero-padded to '022'."""
        cfg = GeneralConfig(umask=22)  # type: ignore[arg-type]
        assert cfg.umask == "022"

    def test_umask_int_single_digit(self) -> None:
        cfg = GeneralConfig(umask=0)  # type: ignore[arg-type]
        assert cfg.umask == "000"

    def test_umask_invalid_octal_raises(self) -> None:
        with pytest.raises(Exception, match="Invalid umask"):
            GeneralConfig(umask="899")

    def test_umask_out_of_range_raises(self) -> None:
        with pytest.raises(Exception, match="out of range"):
            GeneralConfig(umask="1000")

    def test_umask_non_int_non_string_passthrough(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GeneralConfig(umask=[1, 2, 3])  # type: ignore[arg-type]

    def test_custom_puid_pgid(self) -> None:
        cfg = GeneralConfig(puid=500, pgid=600)
        assert cfg.puid == 500
        assert cfg.pgid == 600


# ---------------------------------------------------------------------------
# LogRotationConfig
# ---------------------------------------------------------------------------


class TestLogRotationConfig:
    def test_defaults(self) -> None:
        cfg = LogRotationConfig()
        assert cfg.enabled == DEFAULT_LOG_ROTATION_ENABLED
        assert cfg.max_bytes == DEFAULT_LOG_ROTATION_MAX_BYTES
        assert cfg.backup_count == DEFAULT_LOG_ROTATION_BACKUP_COUNT
        assert cfg.rotate_on_start == DEFAULT_LOG_ROTATION_ROTATE_ON_START

    def test_custom_values(self) -> None:
        cfg = LogRotationConfig(
            enabled=False,
            max_bytes=5_000_000,
            backup_count=10,
            rotate_on_start=False,
        )
        assert cfg.enabled is False
        assert cfg.max_bytes == 5_000_000
        assert cfg.backup_count == 10
        assert cfg.rotate_on_start is False


# ---------------------------------------------------------------------------
# LoggingConfig – rotation field
# ---------------------------------------------------------------------------


class TestLoggingConfigRotation:
    def test_default_rotation(self) -> None:
        cfg = LoggingConfig()
        assert isinstance(cfg.rotation, LogRotationConfig)
        assert cfg.rotation.enabled is True

    def test_custom_rotation(self) -> None:
        cfg = LoggingConfig(
            rotation=LogRotationConfig(
                enabled=False, max_bytes=1024, backup_count=1, rotate_on_start=False
            )
        )
        assert cfg.rotation.enabled is False
        assert cfg.rotation.max_bytes == 1024


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
        assert data is None

    def test_auto_created_config_causes_no_env_var_warnings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Env vars should not trigger 'set in both' warnings against auto-created defaults."""
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        with caplog.at_level(logging.WARNING):
            load_config(tmp_path, "config.yml")
        assert not any("set in both" in r.message for r in caplog.records)

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

    def test_env_var_clash_warning_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Warning subject should include the env var prefix."""
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              level: ERROR
            """,
        )
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        with caplog.at_level(logging.WARNING):
            load_config(tmp_path, "config.yml")
        assert any("'LOG level'" in r.message for r in caplog.records)

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

    def test_config_dir_is_absolute(self, tmp_path: Path) -> None:
        """Config directory should be resolved to absolute path."""
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.config_dir.is_absolute()

    def test_logging_dir_is_absolute_when_given_absolute(self, tmp_path: Path) -> None:
        """An absolute logging directory should remain absolute."""
        log_dir = tmp_path / "logs"
        cfg = load_config(tmp_path, "config.yml", log_dir=log_dir)
        assert cfg.logging.dir is not None
        assert cfg.logging.dir.is_absolute()

    def test_logging_dir_relative_resolved_to_absolute(self, tmp_path: Path) -> None:
        """A relative logging directory should be resolved to an absolute path."""
        cfg = load_config(tmp_path, "config.yml", log_dir=Path("logs"))
        assert cfg.logging.dir is not None
        assert cfg.logging.dir.is_absolute()

    def test_logging_dir_yaml_is_ignored(self, tmp_path: Path) -> None:
        """Logging directory set in YAML should be silently ignored (use env var or CLI)."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            textwrap.dedent("""\
                logging:
                  dir: /custom/yaml/path
            """),
            encoding="utf-8",
        )
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.dir != Path("/custom/yaml/path")

    def test_logging_dir_none_via_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Logging directory can still be disabled via env var."""
        monkeypatch.setenv("LOG_DIR", "")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.dir is None


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


# ---------------------------------------------------------------------------
# load_config – general config
# ---------------------------------------------------------------------------


class TestLoadConfigGeneral:
    """Test general config loading through load_config."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def test_general_defaults_when_section_absent(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.tz == DEFAULT_TZ
        assert cfg.general.puid == DEFAULT_PUID
        assert cfg.general.pgid == DEFAULT_PGID
        assert cfg.general.umask == DEFAULT_UMASK

    def test_general_from_yaml(self, tmp_path: Path) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            general:
              tz: Europe/Berlin
              puid: 500
              pgid: 600
              umask: "077"
            """,
        )
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.tz == "Europe/Berlin"
        assert cfg.general.puid == 500
        assert cfg.general.pgid == 600
        assert cfg.general.umask == "077"

    def test_general_env_var_tz(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.tz == "Asia/Tokyo"

    def test_general_env_var_puid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PUID", "999")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.puid == 999

    def test_general_env_var_pgid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PGID", "888")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.pgid == 888

    def test_general_env_var_umask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("UMASK", "077")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.umask == "077"

    def test_general_env_overrides_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            general:
              tz: UTC
            """,
        )
        monkeypatch.setenv("TZ", "US/Pacific")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.general.tz == "US/Pacific"

    def test_general_env_clash_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Warning should use GENERAL as display prefix for empty-prefix models."""
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            general:
              tz: UTC
            """,
        )
        monkeypatch.setenv("TZ", "US/Eastern")
        with caplog.at_level(logging.WARNING):
            load_config(tmp_path, "config.yml")
        assert any("'GENERAL tz'" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _coerce_typed_list
# ---------------------------------------------------------------------------


class TestCoerceTypedList:
    """Tests for the _coerce_typed_list helper in config.py."""

    def test_non_list_value_returned_unchanged(self) -> None:
        """Non-list values should be passed through as-is (line 188)."""
        from boomarr.config import _coerce_typed_list

        value = {"type": "ffprobe"}
        assert _coerce_typed_list(value) is value

    def test_none_returned_unchanged(self) -> None:
        from boomarr.config import _coerce_typed_list

        assert _coerce_typed_list(None) is None

    def test_list_of_strings_coerced(self) -> None:
        from boomarr.config import _coerce_typed_list

        result = _coerce_typed_list(["ffprobe"])
        assert result == [{"type": "ffprobe"}]

    def test_list_of_dicts_unchanged(self) -> None:
        from boomarr.config import _coerce_typed_list

        item = {"type": "ffprobe"}
        result = _coerce_typed_list([item])
        assert result == [item]


# ---------------------------------------------------------------------------
# _prober_config_from_name / _pre_probe_filter_config_from_name
# ---------------------------------------------------------------------------


class TestConfigHelperFunctions:
    """Tests for the private config helper functions."""

    def test_unknown_prober_type_raises(self) -> None:
        """Fallthrough case in _prober_config_from_name raises ValueError (lines 316-317)."""
        from boomarr.config import _prober_config_from_name

        with pytest.raises(ValueError, match="Unknown prober type"):
            _prober_config_from_name("totally_unknown")

    def test_unknown_pre_probe_filter_type_raises(self) -> None:
        """Fallthrough case in _pre_probe_filter_config_from_name raises ValueError (lines 327-328)."""
        from boomarr.config import _pre_probe_filter_config_from_name

        with pytest.raises(ValueError, match="Unknown pre-probe filter type"):
            _pre_probe_filter_config_from_name("totally_unknown")


# ---------------------------------------------------------------------------
# Config – probers validation
# ---------------------------------------------------------------------------


class TestConfigProbersValidation:
    """Tests for the Config-level probers field_validator."""

    def test_empty_probers_raises(self) -> None:
        """An empty probers list should be rejected by the validator (line 365)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="At least one prober"):
            Config(
                config_dir=Path("."),
                config_file="test.yml",
                general=GeneralConfig(),
                logging=LoggingConfig(),
                probers=[],
            )


# ---------------------------------------------------------------------------
# load_config – log rotation config
# ---------------------------------------------------------------------------


class TestLoadConfigRotation:
    """Test log rotation config loading through load_config."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def test_rotation_defaults_when_absent(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.enabled is True
        assert cfg.logging.rotation.max_bytes == DEFAULT_LOG_ROTATION_MAX_BYTES
        assert cfg.logging.rotation.backup_count == DEFAULT_LOG_ROTATION_BACKUP_COUNT
        assert cfg.logging.rotation.rotate_on_start is True

    def test_rotation_from_yaml(self, tmp_path: Path) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              rotation:
                enabled: false
                max_bytes: 1048576
                backup_count: 5
                rotate_on_start: false
            """,
        )
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.enabled is False
        assert cfg.logging.rotation.max_bytes == 1_048_576
        assert cfg.logging.rotation.backup_count == 5
        assert cfg.logging.rotation.rotate_on_start is False

    def test_rotation_env_var_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_ROTATION_ENABLED", "false")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.enabled is False

    def test_rotation_env_var_max_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_ROTATION_MAX_BYTES", "2097152")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.max_bytes == 2_097_152

    def test_rotation_env_var_backup_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_ROTATION_BACKUP_COUNT", "7")
        cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.backup_count == 7

    def test_rotation_env_overrides_yaml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        self._write_yaml(
            tmp_path / "config.yml",
            """\
            logging:
              rotation:
                enabled: true
            """,
        )
        monkeypatch.setenv("LOG_ROTATION_ENABLED", "false")
        with caplog.at_level(logging.WARNING):
            cfg = load_config(tmp_path, "config.yml")
        assert cfg.logging.rotation.enabled is False
        assert any("LOG_ROTATION_ENABLED" in r.message for r in caplog.records)
