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


class PreProbeFilterType(StrEnum):
    """Discriminator values for pre-probe filter config types."""

    FILE_EXTENSION = "file_extension"


class ProberType(StrEnum):
    """Discriminator values for prober config types."""

    FFPROBE = "ffprobe"


class PostProbeFilterType(StrEnum):
    """Discriminator values for post-probe filter config types."""

    AUDIO_LANGUAGE = "audio_language"


ENV_CONFIG_DIR = "CONFIG_DIR"
ENV_CONFIG_FILE_NAME = "CONFIG_FILE_NAME"
ENV_LOG_LEVEL = "LOG_LEVEL"
ENV_LOG_DIR = "LOG_DIR"
ENV_LOG_FILE_NAME = "LOG_FILE_NAME"
ENV_SKIP_READONLY_CHECK = "SKIP_READONLY_CHECK"

ENV_PREFIX_GENERAL = ""
ENV_PREFIX_LOGGING = "LOG"
ENV_PREFIX_LOG_ROTATION = "LOG_ROTATION"

DEFAULT_CONFIG_DIR = Path("./config")
DEFAULT_CONFIG_FILE_NAME = "boomarr.yml"

DEFAULT_TZ = "UTC"
DEFAULT_PUID = 1000
DEFAULT_PGID = 1000
DEFAULT_UMASK = "022"

DEFAULT_LOG_LEVEL = LogLevel.INFO
DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s: %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_DIR: Path = Path("./config/logs")
DEFAULT_LOG_FILE_NAME: str = "boomarr.log"
DEFAULT_LOG_COLOR = True
DEFAULT_LOG_ROTATION_ENABLED = True
DEFAULT_LOG_ROTATION_MAX_BYTES = 10_485_760  # 10 MB
DEFAULT_LOG_ROTATION_BACKUP_COUNT = 3
DEFAULT_LOG_ROTATION_ROTATE_ON_START = True

CONF_CONFIG_DIR = "config_dir"

CONF_GENERAL = "general"
CONF_GENERAL_TZ = "tz"
CONF_GENERAL_PUID = "puid"
CONF_GENERAL_PGID = "pgid"
CONF_GENERAL_UMASK = "umask"
CONF_LOGGING = "logging"
CONF_LOGGING_LEVEL = "level"
CONF_LOGGING_FORMAT = "format"
CONF_LOGGING_DATE_FORMAT = "date_format"
CONF_LOGGING_DIR = "dir"
CONF_LOGGING_FILE_NAME = "file_name"
CONF_LOGGING_COLOR = "color"
CONF_LOGGING_ROTATION = "rotation"
CONF_LOGGING_ROTATION_ENABLED = "enabled"
CONF_LOGGING_ROTATION_MAX_BYTES = "max_bytes"
CONF_LOGGING_ROTATION_BACKUP_COUNT = "backup_count"
CONF_LOGGING_ROTATION_ROTATE_ON_START = "rotate_on_start"

CONF_PROBERS = "probers"
CONF_PRE_PROBE_FILTERS = "pre_probe_filters"
CONF_SYMLINK_LIBRARIES = "symlink_libraries"

CONF_LIBRARIES = "libraries"
CONF_LIBRARY_NAME = "name"
CONF_LIBRARY_INPUT_PATH = "input_path"
CONF_LIBRARY_OUTPUT_PATH = "output_path"
CONF_OUTPUT_PATH = "output_path"

DEFAULT_PROBERS: list[ProberType] = [ProberType.FFPROBE]
DEFAULT_PRE_PROBE_FILTERS: list[PreProbeFilterType] = [
    PreProbeFilterType.FILE_EXTENSION
]

MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".wmv", ".flv", ".mov", ".webm"}
)
