"""Constants for Boomarr."""

from enum import StrEnum
from pathlib import Path

VERSION = "0.0.0-dev"


class LogLevel(StrEnum):
    """Log level options for console output."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


ENV_CONFIG_DIR = "CONFIG_DIR"
ENV_CONFIG_FILE_NAME = "CONFIG_FILE_NAME"
ENV_LOG_LEVEL = "LOG_LEVEL"

ENV_PREFIX_LOGGING = "LOG"

DEFAULT_CONFIG_DIR = Path("./config")
DEFAULT_CONFIG_FILE_NAME = "config.yml"
DEFAULT_LOG_LEVEL = LogLevel.INFO

CONF_LOGGING = "logging"
CONF_LOGGING_LEVEL = "level"
