"""Collect and render the information shown by ``boomarr status``."""

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from boomarr.config import Config, ScheduleTriggerConfig
from boomarr.const import VERSION
from boomarr.runner import LAST_SCAN_KEY
from boomarr.state import StateStore
from boomarr.symlinks import SymlinkManager


def _triggers(config: Config) -> list[str]:
    triggers: list[str] = []
    for trigger in config.triggers:
        if isinstance(trigger, ScheduleTriggerConfig):
            start = ", on start" if trigger.run_on_start else ""
            triggers.append(f"schedule (every {trigger.interval}s{start})")
        else:  # pragma: no cover - other trigger types are migrated away
            triggers.append(trigger.type.value)
    if config.server.enabled:
        auth = "api key" if config.server.api_key else "no auth"
        triggers.append(f"http server :{config.server.port} (webhooks, {auth})")
    return triggers


def collect_status(config: Config, state: StateStore) -> dict[str, Any]:
    """Return everything ``boomarr status`` shows as a JSON-serialisable dict."""
    symlinks = SymlinkManager()
    libraries: list[dict[str, Any]] = []
    for library in config.libraries:
        outputs: list[dict[str, Any]] = []
        for sym_lib in library.symlink_libraries:
            path = config.symlink_library_output(library, sym_lib)
            outputs.append(
                {
                    "path": str(path),
                    "exists": path.is_dir(),
                    "links": len(symlinks.iter_links(path)),
                    "filters": [f.describe() for f in sym_lib.filters],
                }
            )
        libraries.append(
            {
                "name": library.name,
                "input_path": str(library.input_path),
                "input_available": library.input_path.is_dir(),
                "outputs": outputs,
            }
        )
    return {
        "version": VERSION,
        "cache": state.get_stats(),
        "last_scan": state.get_meta(LAST_SCAN_KEY),
        "triggers": _triggers(config),
        "libraries": libraries,
    }


def _time(timestamp: object) -> str:
    if not isinstance(timestamp, int | float):
        return "never"
    return datetime.fromtimestamp(timestamp).isoformat(sep=" ", timespec="seconds")


def _scan_lines(last: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not last:
        return [("Last scan", "never (run 'boomarr scan' or 'boomarr watch')")]
    lines = [
        (
            "Last scan",
            f"{_time(last.get('finished_at'))} ({last.get('duration_seconds', 0):.1f}s)",
        )
    ]
    if last.get("error"):
        lines.append(("Scan error", str(last["error"])))
    result = last.get("result") or {}
    if result:
        lines.append(
            (
                "Last result",
                f"{result.get('created', 0)} created, {result.get('removed', 0)} removed, "
                f"{result.get('probed', 0)} probed, {result.get('errors', 0)} errors, "
                f"{result.get('blocked', 0)} blocked",
            )
        )
    return lines


def _summary(data: dict[str, Any]) -> list[tuple[str, str]]:
    cache = data["cache"]
    languages = cache.get("languages") or {}
    top = ", ".join(f"{k} ({v})" for k, v in list(languages.items())[:10]) or "-"
    return [
        ("Version", data["version"]),
        *_scan_lines(data.get("last_scan")),
        ("Cached files", str(cache.get("total_cached", 0))),
        ("Without audio", str(cache.get("without_audio", 0))),
        ("Last probe", _time(cache.get("last_probe_time"))),
        ("Audio languages", top),
        ("Triggers", "; ".join(data["triggers"]) or "none"),
    ]


def render_plain(data: dict[str, Any]) -> str:
    """Render status as plain text (for pipes, logs and non-TTY output)."""
    width = max(len(k) for k, _ in _summary(data)) + 2
    lines = [f"{k + ':':<{width}}{v}" for k, v in _summary(data)]
    for library in data["libraries"]:
        state = "" if library["input_available"] else "  [INPUT MISSING]"
        lines.append(f"Library '{library['name']}': {library['input_path']}{state}")
        for out in library["outputs"]:
            missing = "" if out["exists"] else " (not created yet)"
            lines.append(f"  -> {out['path']}: {out['links']} links{missing}")
            lines.append(f"     filters: {' AND '.join(out['filters'])}")
    return "\n".join(lines)


def render_rich(data: dict[str, Any], console: Console) -> None:
    """Render status with tables for interactive terminals."""
    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_column(style="bold cyan")
    summary.add_column()
    for key, value in _summary(data):
        summary.add_row(key, escape(value))
    console.print(summary)

    table = Table(title="Libraries", expand=False)
    table.add_column("Library", style="bold")
    table.add_column("Output")
    table.add_column("Links", justify="right")
    table.add_column("Filters")
    for library in data["libraries"]:
        name = escape(library["name"])
        if not library["input_available"]:
            name += "\n[red]input missing[/red]"
        for idx, out in enumerate(library["outputs"]):
            links = str(out["links"]) if out["exists"] else "[yellow]-[/yellow]"
            table.add_row(
                name if idx == 0 else "",
                escape(out["path"]),
                links,
                escape("\n".join(out["filters"])),
            )
    console.print(table)
