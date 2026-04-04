"""Configuration management module.

Handles loading, parsing, and validation of Boomarr configuration.
"""

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import BaseModel, ValidationError, field_validator

from boomarr.const import (
    CONF_LOGGING,
    CONF_LOGGING_LEVEL,
    DEFAULT_LOG_LEVEL,
    ENV_PREFIX_LOGGING,
    LogLevel,
)


class LoggingConfig(BaseModel):
    """Logging sub-configuration."""

    _env_prefix = ENV_PREFIX_LOGGING

    level: LogLevel = DEFAULT_LOG_LEVEL

    @field_validator(CONF_LOGGING_LEVEL, mode="before")
    @classmethod
    def _coerce_level(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v


class Config(BaseModel):
    """Boomarr root configuration."""

    config_dir: Path
    config_file: str
    logging: LoggingConfig


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
                logging.warning(
                    f"'{name}' is set in both '{config_file_name}' "
                    f"({yaml_data[name]!r}) and {env_var} ({env_value!r}). "
                    "Env var takes precedence."
                )
            merged[name] = env_value
    return merged


def load_config(
    config_dir: Path,
    config_file_name: str,
    log_level: LogLevel | None = None,
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
    if log_level is not None:
        cli_values[CONF_LOGGING] = {CONF_LOGGING_LEVEL: log_level}

    if not config_path.is_file():
        typer.echo(
            f"Config file '{config_path}' not found. Creating with default values..."
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(
                _to_yaml_serializable(
                    {CONF_LOGGING: {CONF_LOGGING_LEVEL: DEFAULT_LOG_LEVEL}}
                ),
                config_file,
            )

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
