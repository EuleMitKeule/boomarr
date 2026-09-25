"""Main entry point for Boomarr CLI.

Defines the Typer CLI application and top-level commands. Serves as the
main execution point when Boomarr is invoked from the command line.
"""

import json
import logging
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from boomarr.config import Config, LibraryConfig, SQLiteDatabaseConfig, load_config
from boomarr.const import (
    APP_NAME,
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE_NAME,
    DEFAULT_HEARTBEAT_FILE_NAME,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE_NAME,
    ENV_CONFIG_DIR,
    ENV_CONFIG_FILE_NAME,
    ENV_HEARTBEAT_FILE,
    ENV_LOG_DIR,
    ENV_LOG_FILE_NAME,
    ENV_LOG_LEVEL,
    ENV_SKIP_READONLY_CHECK,
    HEARTBEAT_MAX_AGE,
    VERSION,
    LogLevel,
)
from boomarr.hooks import build_hooks
from boomarr.log import setup_logging
from boomarr.pipeline import PipelineFactory
from boomarr.processor import LibraryProcessor
from boomarr.runner import PostScanHook, ScanRunner
from boomarr.server import HttpServer
from boomarr.watcher import Watcher

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
# Deliberately ``str``: typer would turn an empty string into Path("."),
# but an empty value must disable file logging.
LogDirOpt = Annotated[
    str | None,
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
        "--dangerous-skip-readonly-check",
        envvar=ENV_SKIP_READONLY_CHECK,
        help="DANGEROUS: Skip the source directory read-only check. For development only — never use in production.",
    ),
]


def _init_config(
    config_dir: Path,
    config_file_name: str,
    log_level: LogLevel | None,
    log_dir: str | None,
    log_file_name: str | None,
) -> Config:
    """Initialize a new config file with default values."""
    config = load_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    setup_logging(config.logging, tz=config.general.tz)
    _LOGGER.info("boomarr version %s startup complete", VERSION)
    for warning in config.warnings:
        _LOGGER.warning(warning)
    _LOGGER.debug("Loaded config: %s", config.model_dump_json(indent=2))
    return config


def _check_probers(config: Config) -> None:
    """Exit early if a configured prober (e.g. ffprobe) is not usable."""
    factory = PipelineFactory()
    for library in config.libraries:
        for prober in factory.for_scan(config, library).probers:
            error = prober.check_available()
            if error is not None:
                _LOGGER.critical(error)
                sys.exit(1)


def _heartbeat_file() -> Path:
    """Return the heartbeat file used by ``watch`` and ``healthcheck``."""
    env = os.environ.get(ENV_HEARTBEAT_FILE)
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / DEFAULT_HEARTBEAT_FILE_NAME


def _build_hooks(config: Config, *, dry_run: bool = False) -> list[PostScanHook]:
    """Create the post-scan hooks (notifications, media server refreshes)."""
    if dry_run:
        return []
    return build_hooks(config)


def verify_source_dirs_readonly(
    libraries: list[LibraryConfig], *, skip: bool = False
) -> None:
    """Verify that all source (input) directories are not writable.

    This is a critical safety check that MUST run before any processing.
    Source directories must be mounted read-only to guarantee that Boomarr
    can never accidentally modify the original media files.

    Pass ``skip=True`` (via ``--dangerous-skip-readonly-check`` or the
    ``DANGEROUS_SKIP_READONLY_CHECK`` env var) to bypass this check during development.

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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Only log which symlinks would be created or removed.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Bypass the removal guard for this scan (e.g. after changing filters).",
        ),
    ] = False,
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
    _check_probers(config)

    state = PipelineFactory.build_state_store(config)
    factory = PipelineFactory(state=state, dry_run=dry_run, force=force)
    runner = ScanRunner(
        config, factory, hooks=_build_hooks(config, dry_run=dry_run), dry_run=dry_run
    )
    try:
        total = runner.run(threading.Event())
    finally:
        state.close()

    _LOGGER.info(
        "Scan complete%s: %d created, %d removed, %d unchanged, %d probed, "
        "%d skipped (cached), %d filtered (non-media), %d errors, %d blocked",
        " (dry run, nothing changed)" if dry_run else "",
        total.created,
        total.removed,
        total.unchanged,
        total.probed,
        total.skipped,
        total.filtered,
        total.errors,
        total.blocked,
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

    if not config.libraries:
        _LOGGER.warning("No libraries configured — nothing to watch")
        return

    _check_probers(config)

    triggers = PipelineFactory.build_triggers(config.triggers)
    if not triggers and not config.server.enabled:
        _LOGGER.warning("No triggers configured — nothing to watch")
        return
    state = PipelineFactory.build_state_store(config)
    factory = PipelineFactory(state=state)
    runner = ScanRunner(config, factory, hooks=_build_hooks(config))

    if config.server.enabled:
        server = config.server
        triggers.append(
            HttpServer(
                host=server.host,
                port=server.port,
                api_key=(server.api_key.get_secret_value() if server.api_key else None),
                metrics_auth=server.metrics_auth,
                status_provider=runner.status,
            )
        )

    watcher = Watcher(
        triggers=triggers,
        scan_callback=runner.run,
        debounce_seconds=config.watch.debounce,
        heartbeat_file=_heartbeat_file(),
    )
    try:
        watcher.run()
    except OSError as exc:
        _LOGGER.critical("Watch mode failed to start: %s", exc)
        sys.exit(1)
    finally:
        state.close()


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

    if isinstance(config.database, SQLiteDatabaseConfig):
        _emit(config.database.db_file.parent)

    for library in config.libraries:
        _emit(config.library_output_base(library))
        for sym_lib in library.symlink_libraries:
            _emit(config.symlink_library_output(library, sym_lib))


@app.command("status", help="Show probe cache statistics.")
def status(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file_name: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
    log_dir: LogDirOpt = None,
    log_file_name: LogFileNameOpt = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """Show probe cache statistics and configured output directories."""
    config = _init_config(
        config_dir, config_file_name, log_level, log_dir, log_file_name
    )
    state = PipelineFactory.build_state_store(config)
    try:
        stats = state.get_stats()
    finally:
        state.close()

    outputs = {
        library.name: [
            str(config.symlink_library_output(library, sym_lib))
            for sym_lib in library.symlink_libraries
        ]
        for library in config.libraries
    }
    if as_json:
        typer.echo(json.dumps({**stats, "outputs": outputs}, indent=2))
        return

    last = stats.get("last_probe_time")
    last_str = (
        datetime.fromtimestamp(last).isoformat(sep=" ", timespec="seconds")
        if last
        else "never"
    )
    typer.echo(f"Boomarr {VERSION}")
    typer.echo(f"Cached files:     {stats.get('total_cached', 0)}")
    typer.echo(f"Without audio:    {stats.get('without_audio', 0)}")
    typer.echo(f"Last probe:       {last_str}")
    languages = stats.get("languages") or {}
    if languages:
        top = ", ".join(
            f"{lang} ({count})" for lang, count in list(languages.items())[:10]
        )
        typer.echo(f"Audio languages:  {top}")
    for name, paths in outputs.items():
        typer.echo(f"Library '{name}':")
        for path in paths:
            typer.echo(f"  -> {path}")


@app.command(
    "healthcheck",
    help="Exit 0 if a running 'watch' process is healthy (for Docker/Kubernetes).",
)
def healthcheck(
    max_age: Annotated[
        float,
        typer.Option(help="Maximum heartbeat age in seconds."),
    ] = HEARTBEAT_MAX_AGE,
) -> None:
    """Check the heartbeat file written by ``boomarr watch``."""
    heartbeat = _heartbeat_file()
    try:
        age = time.time() - heartbeat.stat().st_mtime
    except OSError:
        typer.echo(f"unhealthy: no heartbeat at '{heartbeat}'", err=True)
        raise typer.Exit(1) from None
    if age > max_age:
        typer.echo(f"unhealthy: heartbeat is {age:.0f}s old", err=True)
        raise typer.Exit(1)
    typer.echo(f"healthy: heartbeat {age:.0f}s ago")


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    load_dotenv(override=False)
    app()


if __name__ == "__main__":
    main()
