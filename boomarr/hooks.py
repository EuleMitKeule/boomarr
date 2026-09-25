"""Post-scan hooks: notifications and media server library refreshes."""

import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from boomarr.config import (
    Config,
    EmbyConfig,
    JellyfinConfig,
    NotificationsConfig,
    PathMapping,
    PlexConfig,
    map_to_local,
    map_to_remote,
)
from boomarr.runner import PostScanHook, ScanReport

_LOGGER = logging.getLogger(__name__)


def build_hooks(config: Config) -> list[PostScanHook]:
    """Create all post-scan hooks enabled in *config*."""
    hooks: list[PostScanHook] = []
    if config.notifications.urls:
        hooks.append(NotificationHook(config.notifications))
    for server in config.media_servers:
        match server:
            case PlexConfig():
                hooks.append(PlexRefreshHook(server))
            case JellyfinConfig() | EmbyConfig():
                hooks.append(JellyfinRefreshHook(server))
    return hooks


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationHook:
    """Sends a summary through Apprise when something noteworthy happened."""

    def __init__(self, config: NotificationsConfig) -> None:
        import apprise

        self._config = config
        self._apprise = apprise.Apprise()
        for url in config.urls:
            if not self._apprise.add(url.get_secret_value()):
                _LOGGER.error("Invalid notification URL ignored (check its scheme)")
        self._types = apprise.NotifyType

    def after_scan(self, report: ScanReport) -> None:
        message = self.build_message(report)
        if message is None:
            return
        title, body, failure = message
        notify_type = self._types.FAILURE if failure else self._types.INFO
        if not self._apprise.notify(title=title, body=body, notify_type=notify_type):
            _LOGGER.warning("Sending notification failed")

    def build_message(self, report: ScanReport) -> tuple[str, str, bool] | None:
        """Return ``(title, body, is_failure)`` or None if nothing to send."""
        cfg = self._config
        result = report.result
        if report.error is not None:
            if not cfg.on_errors:
                return None
            return "Boomarr: scan failed", report.error, True

        assert result is not None  # noqa: S101 - no error means a result
        lines: list[str] = []
        failure = False
        if result.blocked and cfg.on_blocked:
            failure = True
            lines.append(
                f"Removal guard blocked {result.blocked} output folder(s). "
                "Run 'boomarr scan --force' if the removals are intended."
            )
        if result.errors and cfg.on_errors:
            failure = True
            lines.append(f"{result.errors} error(s) during the scan, check the logs.")
        if (result.created or result.removed) and cfg.on_changes:
            lines.append(
                f"{result.created} link(s) created, {result.removed} removed in:"
            )
            lines.extend(f"- {out}" for out in report.changed_outputs)
        if not lines:
            return None
        title = "Boomarr: attention needed" if failure else "Boomarr: library updated"
        return title, "\n".join(lines), failure


# ---------------------------------------------------------------------------
# Media servers
# ---------------------------------------------------------------------------


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
) -> bytes:
    if not url.startswith(("http://", "https://")):  # pragma: no cover
        raise ValueError(f"Refusing non-HTTP URL: {url}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, data=body, method=method, headers=headers or {}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data: bytes = response.read()
        return data


def _outputs(report: ScanReport) -> list[Path]:
    return [Path(p) for p in report.changed_outputs]


class PlexRefreshHook:
    """Triggers a partial scan of every Plex section containing a changed output."""

    def __init__(self, config: PlexConfig) -> None:
        self._config = config

    def _headers(self) -> dict[str, str]:
        return {
            "X-Plex-Token": self._config.token.get_secret_value(),
            "Accept": "application/xml",
        }

    def sections(self) -> list[tuple[str, list[str]]]:
        """Return ``(section key, [location paths])`` for all Plex sections."""
        raw = _request(
            f"{self._config.url}/library/sections",
            headers=self._headers(),
            timeout=self._config.timeout,
        )
        root = ET.fromstring(raw)  # noqa: S314 - response of the configured server
        return [
            (
                directory.get("key", ""),
                [loc.get("path", "") for loc in directory.findall("Location")],
            )
            for directory in root.findall("Directory")
        ]

    def after_scan(self, report: ScanReport) -> None:
        outputs = _outputs(report)
        if not outputs:
            return
        mappings = self._config.path_mappings
        sections = self.sections()
        for output in outputs:
            remote = map_to_remote(output, mappings)
            matched = False
            for key, locations in sections:
                for location in locations:
                    local_location = map_to_local(location, mappings)
                    if not (
                        output.is_relative_to(local_location)
                        or local_location.is_relative_to(output)
                    ):
                        continue
                    matched = True
                    query = urllib.parse.urlencode({"path": remote})
                    _request(
                        f"{self._config.url}/library/sections/{key}/refresh?{query}",
                        headers=self._headers(),
                        timeout=self._config.timeout,
                    )
                    _LOGGER.info(
                        "Requested Plex refresh of '%s' (section %s)", remote, key
                    )
            if not matched:
                _LOGGER.warning(
                    "No Plex library contains '%s'; add a library for it or "
                    "configure path_mappings",
                    remote,
                )


class JellyfinRefreshHook:
    """Tells Jellyfin/Emby which output folders changed."""

    def __init__(self, config: JellyfinConfig | EmbyConfig) -> None:
        self._config = config

    def payload(self, report: ScanReport) -> dict[str, Any]:
        mappings: list[PathMapping] = self._config.path_mappings
        return {
            "Updates": [
                {"Path": map_to_remote(out, mappings), "UpdateType": "Modified"}
                for out in _outputs(report)
            ]
        }

    def after_scan(self, report: ScanReport) -> None:
        payload = self.payload(report)
        if not payload["Updates"]:
            return
        _request(
            f"{self._config.url}/Library/Media/Updated",
            method="POST",
            headers={
                "X-Emby-Token": self._config.api_key.get_secret_value(),
                "Content-Type": "application/json",
            },
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._config.timeout,
        )
        _LOGGER.info(
            "Notified %s about %d changed folder(s)",
            self._config.type.value,
            len(payload["Updates"]),
        )
