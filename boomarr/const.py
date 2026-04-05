"""Constants for Boomarr."""

from enum import StrEnum
from pathlib import Path

VERSION = "0.0.0-dev"
APP_NAME = "boomarr"


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
ENV_LOG_DIR = "LOG_DIR"
ENV_LOG_FILE_NAME = "LOG_FILE_NAME"

ENV_PREFIX_LOGGING = "LOG"

DEFAULT_CONFIG_DIR = Path("./config")
DEFAULT_CONFIG_FILE_NAME = "boomarr.yml"
DEFAULT_LOG_LEVEL = LogLevel.INFO
DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s: %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_DIR: Path = Path("./config/logs")
DEFAULT_LOG_FILE_NAME: str = "boomarr.log"
DEFAULT_LOG_COLOR = True

CONF_CONFIG_DIR = "config_dir"
CONF_LOGGING = "logging"
CONF_LOGGING_LEVEL = "level"
CONF_LOGGING_FORMAT = "format"
CONF_LOGGING_DATE_FORMAT = "date_format"
CONF_LOGGING_DIR = "dir"
CONF_LOGGING_FILE_NAME = "file_name"
CONF_LOGGING_COLOR = "color"
