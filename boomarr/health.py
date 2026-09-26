"""Health checks shown in the web UI (System → Health) and used before scans."""

import os
import shutil
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from boomarr.config import Config, FFProbeProberConfig, SQLiteDatabaseConfig
from boomarr.const import AuthMethod


class Level(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Check:
    """One health check result."""

    id: str
    level: Level
    message: str
    wiki: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def writable_inputs(config: Config) -> list[str]:
    """Names of libraries whose source directory is writable (unsafe)."""
    return [
        lib.name
        for lib in config.libraries
        if lib.input_path.is_dir() and os.access(lib.input_path, os.W_OK)
    ]


def _ffprobe_paths(config: Config) -> set[str]:
    configs = list(config.probers)
    for library in config.libraries:
        configs.extend(library.probers or [])
    return {c.path for c in configs if isinstance(c, FFProbeProberConfig)}


def missing_ffprobe(config: Config) -> list[str]:
    """Configured FFprobe executables that cannot be found."""
    return sorted(p for p in _ffprobe_paths(config) if shutil.which(p) is None)


def preflight(config: Config, *, skip_readonly_check: bool) -> str | None:
    """Return why a scan must not run right now, or None."""
    if not config.libraries:
        return "No libraries configured"
    if not skip_readonly_check and (names := writable_inputs(config)):
        return "Source directories must be mounted read-only; writable: " + ", ".join(
            names
        )
    if missing := missing_ffprobe(config):
        return f"FFprobe not found: {', '.join(missing)}"
    return None


def _nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _library_checks(config: Config, *, skip_readonly_check: bool) -> list[Check]:
    checks: list[Check] = []
    if not config.libraries:
        checks.append(
            Check(
                "libraries", Level.WARNING, "No libraries configured yet", "libraries"
            )
        )
    for library in config.libraries:
        cid = f"library:{library.name}"
        if not library.input_path.is_dir():
            checks.append(
                Check(
                    cid,
                    Level.ERROR,
                    f"Source directory '{library.input_path}' of library "
                    f"'{library.name}' does not exist",
                )
            )
            continue
        if not os.access(library.input_path, os.R_OK | os.X_OK):
            checks.append(
                Check(
                    cid,
                    Level.ERROR,
                    f"Source directory '{library.input_path}' is not readable",
                )
            )
        if os.access(library.input_path, os.W_OK):
            level = Level.WARNING if skip_readonly_check else Level.ERROR
            checks.append(
                Check(
                    f"{cid}:readonly",
                    level,
                    f"Source directory '{library.input_path}' is writable; mount it "
                    "read-only" + (" (check disabled)" if skip_readonly_check else ""),
                    "read-only-sources",
                )
            )
        for sym_lib in library.symlink_libraries:
            output = config.symlink_library_output(library, sym_lib)
            base = _nearest_existing(output)
            if not os.access(base, os.W_OK):
                checks.append(
                    Check(
                        f"{cid}:output",
                        Level.ERROR,
                        f"Output directory '{output}' is not writable",
                    )
                )
    return checks


def _config_checks(config: Config, config_writable: bool) -> list[Check]:
    checks: list[Check] = []
    if not config_writable:
        checks.append(
            Check(
                "config",
                Level.WARNING,
                f"'{config.config_dir / config.config_file}' is read-only; "
                "settings cannot be saved from the UI",
            )
        )
    for missing in missing_ffprobe(config):
        checks.append(
            Check(
                "ffprobe",
                Level.ERROR,
                f"FFprobe executable '{missing}' not found",
                "probers",
            )
        )
    if isinstance(config.database, SQLiteDatabaseConfig):
        base = _nearest_existing(config.database.db_file.parent)
        if not os.access(base, os.W_OK):
            checks.append(
                Check(
                    "database",
                    Level.ERROR,
                    f"Database directory '{config.database.dir}' is not writable",
                )
            )
    return checks


def _auth_checks(config: Config, has_credentials: bool) -> list[Check]:
    auth = config.auth
    checks: list[Check] = []
    if auth.method == AuthMethod.NONE:
        checks.append(
            Check(
                "auth",
                Level.WARNING,
                "Authentication is disabled; everyone who can reach Boomarr can "
                "change its settings",
                "authentication",
            )
        )
    elif auth.method == AuthMethod.EXTERNAL and not config.server.trusted_proxies:
        checks.append(
            Check(
                "auth",
                Level.ERROR,
                "External authentication needs 'server.trusted_proxies'; nobody "
                "can log in until it is set",
                "authentication",
            )
        )
    elif auth.method == AuthMethod.FORMS and not has_credentials:
        checks.append(
            Check(
                "auth",
                Level.WARNING,
                "No admin account has been created yet",
                "authentication",
            )
        )
    return checks


def run_checks(
    config: Config,
    *,
    config_writable: bool,
    has_credentials: bool,
    skip_readonly_check: bool,
    restart_required: bool,
    last_scan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Run every check; returns a list sorted by severity."""
    checks = [
        *_library_checks(config, skip_readonly_check=skip_readonly_check),
        *_config_checks(config, config_writable),
        *_auth_checks(config, has_credentials),
    ]
    if restart_required:
        checks.append(
            Check(
                "restart",
                Level.WARNING,
                "Web server settings changed; restart Boomarr to apply them",
            )
        )
    result = (last_scan or {}).get("result") or {}
    if last_scan and last_scan.get("error"):
        checks.append(
            Check("scan", Level.ERROR, f"The last scan failed: {last_scan['error']}")
        )
    elif result.get("blocked"):
        checks.append(
            Check(
                "scan",
                Level.WARNING,
                "The removal guard blocked the last scan; review the changes and "
                "run a forced scan",
                "removal-guard",
            )
        )
    elif result.get("errors"):
        checks.append(
            Check(
                "scan",
                Level.WARNING,
                f"The last scan had {result['errors']} error(s); see the logs",
            )
        )
    order = {Level.ERROR: 0, Level.WARNING: 1, Level.OK: 2}
    return [c.as_dict() for c in sorted(checks, key=lambda c: order[c.level])]
