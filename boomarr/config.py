"""Configuration management module.

Handles loading, parsing, and validation of Boomarr configuration.
"""

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import typer
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from boomarr.const import (
    APP_NAME,
    CONF_CONFIG_DIR,
    CONF_LOGGING,
    CONF_LOGGING_DIR,
    CONF_LOGGING_FILE_NAME,
    CONF_LOGGING_LEVEL,
    DEFAULT_LOG_COLOR,
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    ENV_PREFIX_LOGGING,
    LogLevel,
)

_LOGGER = logging.getLogger(APP_NAME)


class LoggingConfig(BaseModel):
    """Logging sub-configuration."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_LOGGING

    level: LogLevel = Field(default=DEFAULT_LOG_LEVEL, validate_default=True)
    format: str = Field(default=DEFAULT_LOG_FORMAT, validate_default=True)
    date_format: str = Field(default=DEFAULT_LOG_DATE_FORMAT, validate_default=True)
    dir: Path | None = Field(default=DEFAULT_LOG_DIR, validate_default=True)
    file_name: str | None = Field(default=DEFAULT_LOG_FILE_NAME, validate_default=True)
    color: bool = Field(default=DEFAULT_LOG_COLOR, validate_default=True)

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


class Config(BaseModel):
    """Boomarr root configuration."""

    config_dir: Path
    config_file: str
    logging: LoggingConfig

    @field_validator(CONF_CONFIG_DIR, mode="after")
    @classmethod
    def _resolve_config_dir_to_absolute(cls, v: Path) -> Path:
        """Convert config directory path to absolute."""
        return v.resolve()


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
    for name in model_cls.model_fields:
        env_var = f"{prefix}_{name}".upper()
        env_value = os.environ.get(env_var)
        if env_value is not None:
            if name in yaml_data:
                _LOGGER.warning(
                    "'%s %s' is set in both '%s' (%r) and %s (%r). Env var takes precedence.",
                    prefix,
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
        sub_merged = _apply_env_vars(
            field_info.annotation, yaml_sub, config_file_name, field_name
        )
        sub_merged.update(cli_values.get(field_name) or {})
        sub_configs[field_name] = sub_merged

    try:
        _config = Config(
            config_dir=config_dir,
            config_file=config_file_name,
            **sub_configs,
        )
    except ValidationError as exc:
        typer.echo(f"Error validating config file '{config_path}':", err=True)
        typer.echo(exc, err=True)
        sys.exit(1)

    return _config
