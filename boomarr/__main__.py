"""Main entry point for Boomarr CLI.

Defines the Typer CLI application and top-level commands. Serves as the
main execution point when Boomarr is invoked from the command line.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from boomarr.config import Config, LibraryConfig, load_config
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
    ENV_SKIP_READONLY_CHECK,
    VERSION,
    LogLevel,
)
from boomarr.log import setup_logging
from boomarr.models import ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.processor import LibraryProcessor
from boomarr.state import InMemoryStateStore

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
SkipReadonlyCheckOpt = Annotated[
    bool,
    typer.Option(
        "--skip-readonly-check",
        envvar=ENV_SKIP_READONLY_CHECK,
        help="Skip the source directory read-only check. For development only — never use in production.",
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


def verify_source_dirs_readonly(
    libraries: list[LibraryConfig], *, skip: bool = False
) -> None:
    """Verify that all source (input) directories are not writable.

    This is a critical safety check that MUST run before any processing.
    Source directories must be mounted read-only to guarantee that Boomarr
    can never accidentally modify the original media files.

    Pass ``skip=True`` (via ``--skip-readonly-check`` or the
    ``SKIP_READONLY_CHECK`` env var) to bypass this check during development.

    Exits with code 1 if any existing source directory is writable.
    """
    if skip:
        _LOGGER.warning(
            "Source directory read-only check is disabled. "
            "Do NOT use this in production."
        )
        return

    for library in libraries:
        input_path = library.input_path
        if not input_path.is_dir():
            continue
        if os.access(input_path, os.W_OK):
            _LOGGER.critical(
                "Source directory '%s' (library '%s') is writable! "
                "Source directories MUST be mounted read-only to prevent "
                "accidental data modification. Aborting.",
                input_path,
                library.name,
            )
            sys.exit(1)


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
    skip_readonly_check: SkipReadonlyCheckOpt = False,
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

    verify_source_dirs_readonly(config.libraries, skip=skip_readonly_check)

    factory = PipelineFactory()
    total = ScanResult()

    for library in config.libraries:
        pipeline = factory.for_scan(config, library)
        processor = LibraryProcessor(pipeline)
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
    skip_readonly_check: SkipReadonlyCheckOpt = False,
) -> None:
    """Start continuous watch mode.

    Monitors the source library for changes and keeps symlinks up to date
    without requiring manual rescans.
    """
    config = _init_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    _LOGGER.info("Starting watch mode")

    verify_source_dirs_readonly(config.libraries, skip=skip_readonly_check)

    typer.echo("not implemented")


@app.command("clean", help="Run stale symlink cleanup only.")
def clean(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
    skip_readonly_check: SkipReadonlyCheckOpt = False,
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

    verify_source_dirs_readonly(config.libraries, skip=skip_readonly_check)

    factory = PipelineFactory()
    total_removed = 0

    for library in config.libraries:
        pipeline = factory.for_clean(config, library)
        processor = LibraryProcessor(pipeline)
        total_removed += processor.clean_library(library)

    _LOGGER.info("Clean complete: %d stale symlinks removed", total_removed)


@app.command("paths", help="Print all writable paths from config, one per line.")
def paths(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
) -> None:
    """Print all writable paths from config, one per line.

    Outputs the resolved log directory and all symlink library output paths.
    Each path appears exactly once (duplicates are suppressed).
    Suitable for use in the Docker entrypoint to chown writable mounts.
    """
    config = load_config(
        config_dir, config_file_name, log_dir=log_dir, log_file_name=log_file_name
    )

    seen: set[Path] = set()

    def _emit(p: Path | None) -> None:
        if p is not None and p not in seen:
            seen.add(p)
            typer.echo(p)

    _emit(
        config.logging.log_file.parent
        if config.logging.log_file
        else config.logging.dir
    )

    for library in config.libraries:
        base_output: Path | None = (
            library.output_path
            if library.output_path is not None
            else config.output_path
        )
        _emit(base_output)
        for sym_lib in library.symlink_libraries:
            if sym_lib.output_path is not None:
                _emit(sym_lib.output_path)


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

    state = InMemoryStateStore()
    stats = state.get_stats()

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
