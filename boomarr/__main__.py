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


def main() -> None:
    """Main entry point.

    Initializes and runs the CLI application.
    """
    app()


if __name__ == "__main__":
    main()
