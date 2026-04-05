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
from boomarr.models import ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.processor import LibraryProcessor

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
    setup_logging(config.logging, tz=config.general.tz)
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
    config = _init_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    _LOGGER.info("Starting scan")

    if not config.libraries:
        _LOGGER.warning("No libraries configured — nothing to scan")
        return

    factory = PipelineFactory()
    pipeline = factory.for_scan()
    processor = LibraryProcessor(pipeline)
    total = ScanResult()

    for library in config.libraries:
        result = processor.process_library(library)
        total.merge(result)

    _LOGGER.info(
        "Scan complete: %d created, %d removed, %d unchanged, %d skipped, %d errors",
        total.created,
        total.removed,
        total.unchanged,
        total.skipped,
        total.errors,
    )


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
    config = _init_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    _LOGGER.info("Starting clean")

    if not config.libraries:
        _LOGGER.warning("No libraries configured — nothing to clean")
        return

    factory = PipelineFactory()
    pipeline = factory.for_clean()
    processor = LibraryProcessor(pipeline)
    total_removed = 0

    for library in config.libraries:
        total_removed += processor.clean_library(library)

    _LOGGER.info("Clean complete: %d stale symlinks removed", total_removed)


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

    factory = PipelineFactory()
    pipeline = factory.for_scan()
    stats = pipeline.state.get_stats()

    _LOGGER.info(
        "Cache stats: %d total, %d matched, last scan: %s",
        stats.get("total", 0),
        stats.get("matched", 0),
        stats.get("last_scan"),
    )


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    load_dotenv(override=False)
    app()


if __name__ == "__main__":
    main()
