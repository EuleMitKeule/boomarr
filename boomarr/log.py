"""Logging setup for Boomarr.

Configures the ``boomarr`` logger hierarchy from a :class:`~boomarr.config.LoggingConfig`
instance. All sub-module loggers are children of ``boomarr`` and inherit its
handlers automatically.
"""

import logging
import sys

from boomarr.config import LoggingConfig
from boomarr.const import APP_NAME

_LOGGER = logging.getLogger(APP_NAME)

_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[36m",  # Cyan
    logging.INFO: "\033[32m",  # Green
    logging.WARNING: "\033[33m",  # Yellow
    logging.ERROR: "\033[31m",  # Red
    logging.CRITICAL: "\033[1;31m",  # Bold red
}
_ANSI_RESET = "\033[0m"


class _ColoredFormatter(logging.Formatter):
    """Formatter that wraps each log line with an ANSI color based on level."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the formatted log line wrapped in the appropriate ANSI color."""
        color = _LEVEL_COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{_ANSI_RESET}" if color else message


def setup_logging(config: LoggingConfig) -> None:
    """Configure the ``boomarr`` root logger from *config*.

    Sets up a console handler (stderr) and, optionally, a file handler.
    Color is only applied to the console handler and only when stderr is a TTY.

    Args:
        config: The validated :class:`~boomarr.config.LoggingConfig` to apply.
    """
    root = logging.getLogger(APP_NAME)
    root.setLevel(config.level.value)
    root.propagate = False
    root.handlers.clear()

    plain_formatter = logging.Formatter(fmt=config.format, datefmt=config.date_format)

    use_color = config.color and getattr(sys.stderr, "isatty", lambda: False)()
    console_handler = logging.StreamHandler(sys.stderr)
    if use_color:
        console_handler.setFormatter(
            _ColoredFormatter(fmt=config.format, datefmt=config.date_format)
        )
    else:
        console_handler.setFormatter(plain_formatter)
    root.addHandler(console_handler)

    if config.log_file is not None:
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
        file_handler.setFormatter(plain_formatter)
        root.addHandler(file_handler)
