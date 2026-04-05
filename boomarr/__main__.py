"""Main entry point for Boomarr CLI.

Defines the Typer CLI application and top-level commands. Serves as the
main execution point when Boomarr is invoked from the command line.
"""

import logging
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from boomarr.config import Config, load_config
from boomarr.const import (
    APP_NAME,
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE_NAME,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE_NAME,
    ENV_CONFIG_DIR,
    ENV_CONFIG_FILE_NAME,
    ENV_LOG_DIR,
    ENV_LOG_FILE_NAME,
    ENV_LOG_LEVEL,
    VERSION,
    LogLevel,
)
from boomarr.log import setup_logging

_LOGGER = logging.getLogger(APP_NAME)

app = typer.Typer(
    name=APP_NAME,
    help="🔊 Symlink-based audio language filter for Plex & Jellyfin",
    no_args_is_help=True,
)

ConfigDirOpt = Annotated[
    Path,
    typer.Option(
        "--config-dir",
        envvar=ENV_CONFIG_DIR,
        help=f"Config/state directory. Default: '{DEFAULT_CONFIG_DIR}'.",
    ),
]
ConfigFileNameOpt = Annotated[
    str,
    typer.Option(
        "--config-file-name",
        envvar=ENV_CONFIG_FILE_NAME,
        help=f"Config file name. Default: '{DEFAULT_CONFIG_FILE_NAME}'.",
    ),
]
LogLevelOpt = Annotated[
    LogLevel | None,
    typer.Option(
        "--log-level",
        envvar=ENV_LOG_LEVEL,
        help="Log level.",
        case_sensitive=False,
    ),
]
LogDirOpt = Annotated[
    Path | None,
    typer.Option(
        "--log-dir",
        envvar=ENV_LOG_DIR,
        help=f"Log file directory. Default: '{DEFAULT_LOG_DIR}'. Set to empty string to disable file logging.",
    ),
]
LogFileNameOpt = Annotated[
    str | None,
    typer.Option(
        "--log-file-name",
        envvar=ENV_LOG_FILE_NAME,
        help=f"Log file name. Default: '{DEFAULT_LOG_FILE_NAME}'. Set to empty string to disable file logging.",
    ),
]


def _init_config(
    config_dir: Path,
    config_file_name: str,
    log_level: LogLevel | None,
    log_dir: Path | None,
    log_file_name: str | None,
) -> Config:
    """Initialize a new config file with default values."""
    config = load_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    setup_logging(config.logging)
    _LOGGER.info("boomarr version %s startup complete", VERSION)
    _LOGGER.debug("Loaded config: %s", config.model_dump_json(indent=2))
    return config


@app.command("version", help="Show version information.")
def version() -> None:
    """Show version information.

    Displays the current Boomarr version string.
    """
    typer.echo(f"Boomarr version {VERSION}")


@app.command("scan", help="Trigger a one-shot full library scan.")
def scan(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
) -> None:
    """Trigger a one-shot full library scan.

    Walks the source library, creates symlinks for matching audio tracks,
    and exits when complete.
    """
    _init_config(config_dir, config_file_name, log_level, log_dir, log_file_name)
    _LOGGER.info("Starting scan")
    typer.echo("not implemented")


@app.command("watch", help="Start continuous watch mode.")
def watch(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
) -> None:
    """Start continuous watch mode.

    Monitors the source library for changes and keeps symlinks up to date
    without requiring manual rescans.
    """
    _init_config(config_dir, config_file_name, log_level, log_dir, log_file_name)
    _LOGGER.info("Starting watch mode")
    typer.echo("not implemented")


@app.command("clean", help="Run stale symlink cleanup only.")
def clean(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
) -> None:
    """Run stale symlink cleanup only.

    Removes symlinks in the destination directory that no longer correspond
    to a valid source file.
    """
    _init_config(config_dir, config_file_name, log_level, log_dir, log_file_name)
    _LOGGER.info("Starting clean")
    typer.echo("not implemented")


@app.command("status", help="Show cache stats and last run info.")
def status(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
) -> None:
    """Show cache stats and last run info.

    Displays a summary of the current cache state and when the last scan
    was performed.
    """
    _init_config(config_dir, config_file_name, log_level, log_dir, log_file_name)
    _LOGGER.info("Showing status")
    typer.echo("not implemented")


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    load_dotenv(override=False)
    app()


if __name__ == "__main__":
    main()
