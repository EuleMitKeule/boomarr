""" "Test" buttons of the settings pages (probers, media servers, notifications)."""

import asyncio
import shutil
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from boomarr.config import (
    AnyMediaServerConfig,
    AnyProberConfig,
    EmbyConfig,
    FFProbeProberConfig,
    JellyfinConfig,
    NotificationsConfig,
    PlexConfig,
    clean_loc,
    clean_msg,
)

_PROBER = TypeAdapter(AnyProberConfig)
_MEDIA_SERVER = TypeAdapter(AnyMediaServerConfig)

Result = tuple[bool, str]


def _first_error(exc: ValidationError, data: Any) -> str:
    error = exc.errors()[0]
    loc = ".".join(str(p) for p in clean_loc(error["loc"], data))
    msg = clean_msg(error["msg"])
    return f"{loc}: {msg}" if loc else msg


async def _ffprobe(config: FFProbeProberConfig) -> Result:
    executable = shutil.which(config.path)
    if executable is None:
        return False, f"'{config.path}' was not found"
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except (OSError, TimeoutError) as exc:
        return False, f"Cannot run '{executable}': {exc}"
    first_line = stdout.decode(errors="replace").splitlines()[:1]
    if process.returncode != 0 or not first_line:
        return False, f"'{executable}' did not report a version"
    return True, first_line[0]


async def _get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await client.get(url, headers=headers)


def _http_error(response: httpx.Response) -> Result:
    if response.status_code in {401, 403}:
        return (
            False,
            f"Authentication failed (HTTP {response.status_code}); check the key",
        )
    return False, f"Unexpected response: HTTP {response.status_code}"


async def _prober(data: Any) -> Result:
    try:
        config = _PROBER.validate_python(data)
    except ValidationError as exc:
        return False, _first_error(exc, data)
    if isinstance(config, FFProbeProberConfig):
        return await _ffprobe(config)
    response = await _get(
        f"{config.url}/api/v3/system/status",
        {"X-Api-Key": config.api_key.get_secret_value(), "Accept": "application/json"},
        config.timeout,
    )
    if response.status_code != 200:
        return _http_error(response)
    info = response.json()
    return (
        True,
        f"{info.get('appName', config.type.value)} {info.get('version', '')}".strip(),
    )


async def _media_server(data: Any) -> Result:
    try:
        config = _MEDIA_SERVER.validate_python(data)
    except ValidationError as exc:
        return False, _first_error(exc, data)
    if isinstance(config, PlexConfig):
        response = await _get(
            f"{config.url}/library/sections",
            {
                "X-Plex-Token": config.token.get_secret_value(),
                "Accept": "application/json",
            },
            config.timeout,
        )
        if response.status_code != 200:
            return _http_error(response)
        container = response.json().get("MediaContainer", {})
        count = len(container.get("Directory", []))
        return True, f"Connected to Plex ({count} libraries)"
    assert isinstance(config, JellyfinConfig | EmbyConfig)  # noqa: S101 - union exhausted
    response = await _get(
        f"{config.url}/System/Info",
        {
            "X-Emby-Token": config.api_key.get_secret_value(),
            "Accept": "application/json",
        },
        config.timeout,
    )
    if response.status_code != 200:
        return _http_error(response)
    info = response.json()
    name = info.get("ServerName") or config.type.value
    return True, f"Connected to {name} {info.get('Version', '')}".strip()


def _notify(config: NotificationsConfig) -> Result:
    import apprise

    sender = apprise.Apprise()
    for url in config.urls:
        if not sender.add(url.get_secret_value()):
            return False, "A notification URL is invalid (check its scheme)"
    if not config.urls:
        return False, "No notification URLs configured"
    if not sender.notify(
        title="Boomarr", body="This is a test notification from Boomarr."
    ):
        return False, "Sending failed; see the logs for details"
    return True, f"Test notification sent to {len(config.urls)} target(s)"


async def _notifications(data: Any) -> Result:
    try:
        config = NotificationsConfig.model_validate(data)
    except ValidationError as exc:
        return False, _first_error(exc, data)
    return await asyncio.to_thread(_notify, config)


_TESTS = {
    "prober": _prober,
    "media_server": _media_server,
    "notifications": _notifications,
}


async def test(kind: str, data: Any) -> Result:
    """Run the test for *kind*; returns ``(ok, human readable message)``."""
    handler = _TESTS.get(kind)
    if handler is None:
        return False, f"Unknown test '{kind}'"
    try:
        return await handler(data)
    except httpx.HTTPError as exc:
        return False, f"Connection failed: {exc}"
    except ValueError as exc:
        return False, f"Invalid response: {exc}"
