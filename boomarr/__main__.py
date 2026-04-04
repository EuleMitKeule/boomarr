"""Main entry point for Boomarr CLI.

Defines the Typer CLI application and top-level commands. Serves as the
main execution point when Boomarr is invoked from the command line.
"""

import typer

from boomarr.const import VERSION

app = typer.Typer(
    name="boomarr",
    help="🔊 Symlink-based audio language filter for Plex & Jellyfin",
)


@app.command(
    "version",
    help="Show version information",
)
def version() -> None:
    """Show version information.

    Displays the current Boomarr version string.
    """
    typer.echo(f"Boomarr version {VERSION}")


@app.command(
    "scan",
    help="Trigger a one-shot full library scan.",
)
def scan() -> None:
    """Trigger a one-shot full library scan.

    Walks the source library, creates symlinks for matching audio tracks,
    and exits when complete.
    """
    typer.echo("not implemented")


@app.command(
    "watch",
    help="Start continuous watch mode.",
)
def watch() -> None:
    """Start continuous watch mode.

    Monitors the source library for changes and keeps symlinks up to date
    without requiring manual rescans.
    """
    typer.echo("not implemented")


@app.command(
    "clean",
    help="Run stale symlink cleanup only.",
)
def clean() -> None:
    """Run stale symlink cleanup only.

    Removes symlinks in the destination directory that no longer correspond
    to a valid source file.
    """
    typer.echo("not implemented")


@app.command(
    "status",
    help="Show cache stats and last run info.",
)
def status() -> None:
    """Show cache stats and last run info.

    Displays a summary of the current cache state and when the last scan
    was performed.
    """
    typer.echo("not implemented")


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    app()


if __name__ == "__main__":
    main()
