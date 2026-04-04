"""Main entry point for Boomarr CLI.

Defines the Typer CLI application and top-level commands. Serves as the
main execution point when Boomarr is invoked from the command line.
"""

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from boomarr.config import load_config
from boomarr.const import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE_NAME,
    ENV_CONFIG_DIR,
    ENV_CONFIG_FILE_NAME,
    ENV_LOG_LEVEL,
    VERSION,
    LogLevel,
)

app = typer.Typer(
    name="boomarr",
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


@app.command("version", help="Show version information.")
def version() -> None:
    """Show version information.

    Displays the current Boomarr version string.
    """
    typer.echo(f"Boomarr version {VERSION}")


@app.command("scan", help="Trigger a one-shot full library scan.")
def scan(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
) -> None:
    """Trigger a one-shot full library scan.

    Walks the source library, creates symlinks for matching audio tracks,
    and exits when complete.
    """
    load_config(config_dir, config_file, log_level)
    typer.echo("not implemented")


@app.command("watch", help="Start continuous watch mode.")
def watch(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
) -> None:
    """Start continuous watch mode.

    Monitors the source library for changes and keeps symlinks up to date
    without requiring manual rescans.
    """
    load_config(config_dir, config_file, log_level)
    typer.echo("not implemented")


@app.command("clean", help="Run stale symlink cleanup only.")
def clean(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
) -> None:
    """Run stale symlink cleanup only.

    Removes symlinks in the destination directory that no longer correspond
    to a valid source file.
    """
    load_config(config_dir, config_file, log_level)
    typer.echo("not implemented")


@app.command("status", help="Show cache stats and last run info.")
def status(
    config_dir: ConfigDirOpt = DEFAULT_CONFIG_DIR,
    config_file: ConfigFileNameOpt = DEFAULT_CONFIG_FILE_NAME,
    log_level: LogLevelOpt = None,
) -> None:
    """Show cache stats and last run info.

    Displays a summary of the current cache state and when the last scan
    was performed.
    """
    load_config(config_dir, config_file, log_level)
    typer.echo("not implemented")


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    load_dotenv(override=False)
    app()


if __name__ == "__main__":
    main()
