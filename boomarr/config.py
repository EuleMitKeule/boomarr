"""Configuration management module.

Handles loading, parsing, and validation of Boomarr configuration.
"""

import logging
import os
import sys
import zoneinfo
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Literal

import typer
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from boomarr.const import (
    APP_NAME,
    CONF_CONFIG_DIR,
    CONF_DATABASE,
    CONF_DATABASE_DIR,
    CONF_GENERAL_TZ,
    CONF_GENERAL_UMASK,
    CONF_LIBRARIES,
    CONF_LIBRARY_INPUT_PATH,
    CONF_LIBRARY_NAME,
    CONF_LIBRARY_OUTPUT_PATH,
    CONF_LOGGING,
    CONF_LOGGING_DIR,
    CONF_LOGGING_FILE_NAME,
    CONF_LOGGING_LEVEL,
    CONF_OUTPUT_PATH,
    DEFAULT_DB_DIR,
    DEFAULT_DB_FILE_NAME,
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
    DEFAULT_PRE_PROBE_FILTERS,
    DEFAULT_PROBERS,
    DEFAULT_PUID,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_RUN_ON_START,
    DEFAULT_TZ,
    DEFAULT_UMASK,
    DEFAULT_WATCH_DEBOUNCE,
    ENV_PREFIX_GENERAL,
    ENV_PREFIX_LOG_ROTATION,
    ENV_PREFIX_LOGGING,
    DatabaseType,
    LogLevel,
    PostProbeFilterType,
    PreProbeFilterType,
    ProberType,
    TriggerType,
)

__all__ = [
    "AnyDatabaseConfig",
    "AnyTriggerConfig",
    "DatabaseType",
    "MemoryDatabaseConfig",
    "PostProbeFilterType",
    "PreProbeFilterType",
    "ProberType",
    "ScheduleTriggerConfig",
    "SQLiteDatabaseConfig",
    "TriggerType",
    "WatchConfig",
]

_LOGGER = logging.getLogger(APP_NAME)


class GeneralConfig(BaseModel):
    """General sub-configuration for timezone, user/group IDs, and umask."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_GENERAL

    tz: str = Field(default=DEFAULT_TZ, validate_default=True)
    puid: int = Field(default=DEFAULT_PUID, validate_default=True)
    pgid: int = Field(default=DEFAULT_PGID, validate_default=True)
    umask: str = Field(default=DEFAULT_UMASK, validate_default=True)

    @field_validator(CONF_GENERAL_TZ, mode="before")
    @classmethod
    def _coerce_tz(cls, v: object) -> object:
        """Treat empty/whitespace-only strings as None (falls back to default)."""
        if isinstance(v, str) and not v.strip():
            return DEFAULT_TZ
        return v

    @field_validator(CONF_GENERAL_TZ, mode="after")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        """Validate that the timezone is a known IANA timezone."""
        try:
            zoneinfo.ZoneInfo(v)
        except KeyError:
            raise ValueError(f"Invalid timezone: '{v}'")
        return v

    @field_validator(CONF_GENERAL_UMASK, mode="before")
    @classmethod
    def _coerce_umask(cls, v: object) -> object:
        """Convert integer umask values (from YAML) to zero-padded strings."""
        if isinstance(v, int):
            return f"{v:03d}"
        return v

    @field_validator(CONF_GENERAL_UMASK, mode="after")
    @classmethod
    def _validate_umask(cls, v: str) -> str:
        """Validate that the umask is a valid octal string in range 000-777."""
        try:
            val = int(v, 8)
        except ValueError:
            raise ValueError(
                f"Invalid umask '{v}': must be a valid octal string (e.g. '022')"
            )
        if val < 0 or val > 0o777:
            raise ValueError(f"Umask value '{v}' out of range (000-777)")
        return v


class LogRotationConfig(BaseModel):
    """Log file rotation sub-configuration."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_LOG_ROTATION

    enabled: bool = Field(default=DEFAULT_LOG_ROTATION_ENABLED, validate_default=True)
    max_bytes: int = Field(
        default=DEFAULT_LOG_ROTATION_MAX_BYTES, validate_default=True
    )
    backup_count: int = Field(
        default=DEFAULT_LOG_ROTATION_BACKUP_COUNT, validate_default=True
    )
    rotate_on_start: bool = Field(
        default=DEFAULT_LOG_ROTATION_ROTATE_ON_START, validate_default=True
    )


class LoggingConfig(BaseModel):
    """Logging sub-configuration."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_LOGGING
    _yaml_excluded: ClassVar[frozenset[str]] = frozenset({CONF_LOGGING_DIR})

    level: LogLevel = Field(default=DEFAULT_LOG_LEVEL, validate_default=True)
    format: str = Field(default=DEFAULT_LOG_FORMAT, validate_default=True)
    date_format: str = Field(default=DEFAULT_LOG_DATE_FORMAT, validate_default=True)
    dir: Path | None = Field(default=DEFAULT_LOG_DIR, validate_default=True)
    file_name: str | None = Field(default=DEFAULT_LOG_FILE_NAME, validate_default=True)
    color: bool = Field(default=DEFAULT_LOG_COLOR, validate_default=True)
    rotation: LogRotationConfig = Field(
        default_factory=LogRotationConfig, validate_default=True
    )

    @property
    def log_file(self) -> Path | None:
        """Return the resolved log file path, or None if file logging is disabled."""
        if self.dir is None or self.file_name is None:
            return None
        return self.dir / self.file_name

    @field_validator(CONF_LOGGING_LEVEL, mode="before")
    @classmethod
    def _coerce_level(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator(CONF_LOGGING_DIR, CONF_LOGGING_FILE_NAME, mode="before")
    @classmethod
    def _coerce_nullable_str(cls, v: object) -> object:
        """Treat empty-string values as None (disables file logging)."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(CONF_LOGGING_DIR, mode="after")
    @classmethod
    def _resolve_dir_to_absolute(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v


def _coerce_typed_list(v: object) -> object:
    """Coerce plain string items in a list to ``{'type': item}`` dicts.

    Allows YAML entries like ``- ffprobe`` in addition to
    ``- type: ffprobe`` for configs without required arguments.
    StrEnum members are also strings, so they are handled by the same branch.
    """
    if isinstance(v, list):
        return [{"type": item} if isinstance(item, str) else item for item in v]
    return v


class ProberConfig(BaseModel):
    """Base class for prober configurations."""

    type: ProberType


class FFProbeProberConfig(ProberConfig):
    """Configuration for the FFProbe prober."""

    type: Literal[ProberType.FFPROBE] = ProberType.FFPROBE


AnyProberConfig = FFProbeProberConfig


class PreProbeFilterConfig(BaseModel):
    """Base class for pre-probe filter configurations."""

    type: PreProbeFilterType


class FileExtensionFilterConfig(PreProbeFilterConfig):
    """Configuration for the file-extension pre-probe filter."""

    type: Literal[PreProbeFilterType.FILE_EXTENSION] = PreProbeFilterType.FILE_EXTENSION
    extensions: list[str] | None = None


AnyPreProbeFilterConfig = FileExtensionFilterConfig


class PostProbeFilterConfig(BaseModel):
    """Base class for post-probe filter configurations."""

    type: PostProbeFilterType
    suffix: str | None = None


class AudioLanguageFilterConfig(PostProbeFilterConfig):
    """Configuration for the audio-language post-probe filter."""

    type: Literal[PostProbeFilterType.AUDIO_LANGUAGE] = (
        PostProbeFilterType.AUDIO_LANGUAGE
    )
    languages: list[str]

    @field_validator("languages", mode="after")
    @classmethod
    def _validate_languages_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one language is required")
        return v


AnyPostProbeFilterConfig = AudioLanguageFilterConfig


class TriggerConfig(BaseModel):
    """Base class for trigger source configurations."""

    type: TriggerType


class ScheduleTriggerConfig(TriggerConfig):
    """Configuration for the periodic schedule trigger.

    Triggers a full rescan at a fixed interval.  When ``run_on_start``
    is ``True`` (the default) an immediate scan is emitted before the
    first interval elapses.
    """

    type: Literal[TriggerType.SCHEDULE] = TriggerType.SCHEDULE
    interval: int = Field(default=DEFAULT_SCHEDULE_INTERVAL, validate_default=True)
    run_on_start: bool = Field(
        default=DEFAULT_SCHEDULE_RUN_ON_START, validate_default=True
    )

    @field_validator("interval", mode="after")
    @classmethod
    def _validate_interval_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("interval must be a positive number of seconds")
        return v


AnyTriggerConfig = ScheduleTriggerConfig


class WatchConfig(BaseModel):
    """Watch-mode sub-configuration."""

    _env_prefix: ClassVar[str] = "WATCH"

    debounce: float = Field(default=DEFAULT_WATCH_DEBOUNCE, validate_default=True)

    @field_validator("debounce", mode="after")
    @classmethod
    def _validate_debounce_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("debounce must be non-negative")
        return v


class SymlinkLibraryConfig(BaseModel):
    """Configuration for a single symlink library output."""

    name: str | None = None
    filters: list[AnyPostProbeFilterConfig]
    output_path: Path | None = None

    @field_validator("filters", mode="after")
    @classmethod
    def _validate_filters_not_empty(
        cls,
        v: list[AnyPostProbeFilterConfig],
    ) -> list[AnyPostProbeFilterConfig]:
        if not v:
            raise ValueError("Symlink library must have at least one filter")
        return v

    @field_validator("output_path", mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v


class LibraryConfig(BaseModel):
    """Per-library configuration."""

    name: str
    input_path: Path
    output_path: Path | None = None
    probers: list[AnyProberConfig] | None = None
    pre_probe_filters: list[AnyPreProbeFilterConfig] | None = None
    symlink_libraries: list[SymlinkLibraryConfig]

    @field_validator("probers", "pre_probe_filters", mode="before")
    @classmethod
    def _coerce_to_typed_dicts(cls, v: object) -> object:
        return _coerce_typed_list(v)

    @field_validator(CONF_LIBRARY_NAME, mode="after")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Library name must not be empty")
        return v.strip()

    @field_validator(CONF_LIBRARY_INPUT_PATH, mode="after")
    @classmethod
    def _resolve_input_path(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator(CONF_LIBRARY_OUTPUT_PATH, mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v

    @field_validator("symlink_libraries", mode="after")
    @classmethod
    def _validate_symlink_libraries_not_empty(
        cls,
        v: list[SymlinkLibraryConfig],
    ) -> list[SymlinkLibraryConfig]:
        if not v:
            raise ValueError("Library must have at least one symlink library")
        return v


def _prober_config_from_name(prober_type: ProberType | str) -> AnyProberConfig:
    """Build the appropriate ProberConfig subclass from a prober type (enum or string)."""
    match prober_type:
        case ProberType.FFPROBE:
            return FFProbeProberConfig()
        case _:
            raise ValueError(f"Unknown prober type: {prober_type!r}")


def _pre_probe_filter_config_from_name(
    filter_type: PreProbeFilterType | str,
) -> AnyPreProbeFilterConfig:
    """Build the appropriate PreProbeFilterConfig subclass from a filter type (enum or string)."""
    match filter_type:
        case PreProbeFilterType.FILE_EXTENSION:
            return FileExtensionFilterConfig()
        case _:
            raise ValueError(f"Unknown pre-probe filter type: {filter_type!r}")


class MemoryDatabaseConfig(BaseModel):
    """In-memory (non-persistent) database backend configuration."""

    type: Literal[DatabaseType.MEMORY] = DatabaseType.MEMORY


class SQLiteDatabaseConfig(BaseModel):
    """SQLite database backend configuration."""

    type: Literal[DatabaseType.SQLITE] = DatabaseType.SQLITE
    dir: Path = Field(default=DEFAULT_DB_DIR, validate_default=True)
    file_name: str = Field(default=DEFAULT_DB_FILE_NAME)

    @property
    def db_file(self) -> Path:
        """Return the resolved path to the SQLite database file."""
        return self.dir / self.file_name

    @field_validator(CONF_DATABASE_DIR, mode="after")
    @classmethod
    def _resolve_dir_to_absolute(cls, v: Path) -> Path:
        return v.resolve()


AnyDatabaseConfig = MemoryDatabaseConfig | SQLiteDatabaseConfig


class Config(BaseModel):
    """Boomarr root configuration."""

    config_dir: Path
    config_file: str
    general: GeneralConfig
    logging: LoggingConfig
    database: AnyDatabaseConfig = Field(
        default_factory=SQLiteDatabaseConfig, discriminator="type"
    )
    output_path: Path | None = None
    watch: WatchConfig = Field(default_factory=WatchConfig)
    probers: list[AnyProberConfig] = Field(
        default_factory=lambda: [_prober_config_from_name(n) for n in DEFAULT_PROBERS],
    )
    pre_probe_filters: list[AnyPreProbeFilterConfig] = Field(
        default_factory=lambda: [
            _pre_probe_filter_config_from_name(n) for n in DEFAULT_PRE_PROBE_FILTERS
        ],
    )
    triggers: list[AnyTriggerConfig] = Field(
        default_factory=lambda: [ScheduleTriggerConfig()]
    )
    libraries: list[LibraryConfig] = Field(default_factory=list)

    @field_validator("probers", "pre_probe_filters", "triggers", mode="before")
    @classmethod
    def _coerce_to_typed_dicts(cls, v: object) -> object:
        return _coerce_typed_list(v)

    @field_validator(CONF_CONFIG_DIR, mode="after")
    @classmethod
    def _resolve_config_dir_to_absolute(cls, v: Path) -> Path:
        """Convert config directory path to absolute."""
        return v.resolve()

    @field_validator(CONF_OUTPUT_PATH, mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v

    @field_validator("probers", mode="after")
    @classmethod
    def _validate_probers_not_empty(
        cls, v: list[AnyProberConfig]
    ) -> list[AnyProberConfig]:
        if not v:
            raise ValueError("At least one prober is required")
        return v

    @field_validator(CONF_LIBRARIES, mode="after")
    @classmethod
    def _validate_unique_library_names(
        cls, v: list[LibraryConfig]
    ) -> list[LibraryConfig]:
        names = [lib.name for lib in v]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate library names: {set(dupes)}")
        return v

    @model_validator(mode="after")
    def _validate_output_paths(self) -> "Config":
        """Ensure every library can resolve an output path.

        Either the global ``output_path`` is set, or each library provides
        its own ``output_path``, or a combination of both.
        """
        if self.output_path is None:
            missing = [lib.name for lib in self.libraries if lib.output_path is None]
            if missing:
                raise ValueError(
                    f"Global output_path is not set and these libraries "
                    f"are missing output_path: {missing}"
                )
        return self


_config: Config | None = None


def get_config() -> Config:
    """Return the loaded Config singleton.

    Raises:
        RuntimeError: If load_config() has not been called yet.
    """
    if _config is None:
        raise RuntimeError("Config has not been loaded yet. Call load_config() first.")
    return _config


def _to_yaml_serializable(obj: Any) -> Any:
    """Recursively convert enums and other non-YAML types to YAML-serializable forms."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_yaml_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_yaml_serializable(v) for v in obj]
    return obj


def _apply_env_vars(
    model_cls: type[BaseModel],
    yaml_data: dict[str, Any],
    config_file_name: str,
    field_name: str,
) -> dict[str, Any]:
    """Overlay environment variables onto ``yaml_data`` for ``model_cls``.

    The env var prefix is read from the model class's ``_env_prefix`` attribute
    if present, otherwise defaults to the field name in uppercase.
    Field names are derived as ``f"{prefix}_{field_name}".upper()``.

    Warns when the same field is supplied by both the config file
    and an env var (the env var wins).

    Args:
        model_cls: The Pydantic model whose fields to inspect.
        yaml_data: Values already loaded from the config file.
        config_file_name: File name used in the warning message.
        field_name: The name of the field in the parent config class.

    Returns:
        A new dict with env var values overlaid on top of yaml_data.
    """
    prefix: str = getattr(model_cls, "_env_prefix", field_name.upper())
    merged = dict(yaml_data)
    for name, field_info in model_cls.model_fields.items():
        if isinstance(field_info.annotation, type) and issubclass(
            field_info.annotation, BaseModel
        ):
            nested_yaml = merged.get(name) or {}
            merged[name] = _apply_env_vars(
                field_info.annotation, nested_yaml, config_file_name, name
            )
            continue
        env_var = f"{prefix}_{name}".upper() if prefix else name.upper()
        env_value = os.environ.get(env_var)
        if env_value is not None:
            if name in yaml_data:
                display_prefix = prefix if prefix else field_name.upper()
                _LOGGER.warning(
                    "'%s %s' is set in both '%s' (%r) and %s (%r). Env var takes precedence.",
                    display_prefix,
                    name,
                    config_file_name,
                    yaml_data[name],
                    env_var,
                    env_value,
                )
            merged[name] = env_value
    return merged


def load_config(
    config_dir: Path,
    config_file_name: str,
    log_level: LogLevel | None = None,
    log_dir: Path | None = None,
    log_file_name: str | None = None,
) -> Config:
    """Load and validate configuration from all sources.

    Exits:
        Calls sys.exit() with a human-readable error on validation failure.

    Returns:
        The validated Config singleton.
    """
    global _config

    config_path = config_dir / config_file_name
    cli_values: dict[str, dict[str, Any]] = {}
    logging_cli: dict[str, Any] = {}
    if log_level is not None:
        logging_cli[CONF_LOGGING_LEVEL] = log_level
    if log_dir is not None:
        logging_cli[CONF_LOGGING_DIR] = log_dir
    if log_file_name is not None:
        logging_cli[CONF_LOGGING_FILE_NAME] = log_file_name
    if logging_cli:
        cli_values[CONF_LOGGING] = logging_cli

    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.touch(exist_ok=True)
        # TODO: Write template config file

    with config_path.open(encoding="utf-8") as config_file:
        yaml_data = yaml.safe_load(config_file) or {}

    sub_configs: dict[str, Any] = {}
    for field_name, field_info in Config.model_fields.items():
        if not (
            isinstance(field_info.annotation, type)
            and issubclass(field_info.annotation, BaseModel)
        ):
            continue
        yaml_sub = yaml_data.get(field_name) or {}
        yaml_excluded: frozenset[str] = getattr(
            field_info.annotation, "_yaml_excluded", frozenset()
        )
        yaml_sub = {k: v for k, v in yaml_sub.items() if k not in yaml_excluded}
        sub_merged = _apply_env_vars(
            field_info.annotation, yaml_sub, config_file_name, field_name
        )
        sub_merged.update(cli_values.get(field_name) or {})
        sub_configs[field_name] = sub_merged

    libraries_raw = yaml_data.get(CONF_LIBRARIES) or []

    extra_fields: dict[str, Any] = {}
    probers_raw = yaml_data.get("probers")
    if probers_raw is not None:
        extra_fields["probers"] = probers_raw
    pre_probe_raw = yaml_data.get("pre_probe_filters")
    if pre_probe_raw is not None:
        extra_fields["pre_probe_filters"] = pre_probe_raw
    triggers_raw = yaml_data.get("triggers")
    if triggers_raw is not None:
        extra_fields["triggers"] = triggers_raw
    output_path_raw = yaml_data.get("output_path")
    if output_path_raw is not None:
        extra_fields["output_path"] = output_path_raw
    database_raw = yaml_data.get(CONF_DATABASE)
    resolved_config_dir = config_dir.resolve()
    if database_raw is None:
        # Default: sqlite stored alongside the config file
        extra_fields[CONF_DATABASE] = {
            "type": DatabaseType.SQLITE,
            "dir": str(resolved_config_dir),
        }
    else:
        db_raw = dict(database_raw)
        db_type = str(db_raw.get("type", DatabaseType.SQLITE))
        if db_type == DatabaseType.SQLITE and "dir" not in db_raw:
            db_raw["dir"] = str(resolved_config_dir)
        extra_fields[CONF_DATABASE] = db_raw

    try:
        _config = Config(
            config_dir=config_dir,
            config_file=config_file_name,
            libraries=libraries_raw,
            **sub_configs,
            **extra_fields,
        )
    except ValidationError as exc:
        typer.echo(f"Error validating config file '{config_path}':", err=True)
        typer.echo(exc, err=True)
        sys.exit(1)

    return _config
