"""Tests for the connection test buttons (boomarr.web.connections)."""

import asyncio
import sys
from pathlib import Path
from typing import Any

import apprise
import httpx
import pytest
import respx

from boomarr.web import connections


def _test(kind: str, data: Any) -> tuple[bool, str]:
    return asyncio.run(connections.test(kind, data))


def _script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "fake-ffprobe"
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(0o755)
    return str(path)


class TestFFprobe:
    def test_real_binary(self, tmp_path: Path) -> None:
        ok, message = _test(
            "prober",
            {
                "type": "ffprobe",
                "path": _script(tmp_path, "print('ffprobe version 7.1')"),
            },
        )
        assert (ok, message) == (True, "ffprobe version 7.1")

    def test_missing(self) -> None:
        assert _test("prober", {"type": "ffprobe", "path": "no-such-binary"}) == (
            False,
            "'no-such-binary' was not found",
        )

    def test_bad_exit(self, tmp_path: Path) -> None:
        ok, message = _test(
            "prober",
            {"type": "ffprobe", "path": _script(tmp_path, "raise SystemExit(1)")},
        )
        assert not ok and "did not report a version" in message

    def test_not_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "ffprobe"
        path.write_text("")
        monkeypatch.setattr(connections.shutil, "which", lambda _: str(path))
        ok, message = _test("prober", {"type": "ffprobe", "path": "ffprobe"})
        assert not ok and message.startswith("Cannot run")

    def test_validation_error(self) -> None:
        ok, message = _test("prober", {"type": "ffprobe", "timeout": -1})
        assert not ok and message.startswith("timeout:")


ARR = {"type": "sonarr", "url": "http://sonarr:8989", "api_key": "k"}


class TestArr:
    @respx.mock
    def test_ok(self) -> None:
        route = respx.get("http://sonarr:8989/api/v3/system/status").respond(
            json={"appName": "Sonarr", "version": "4.0.1"}
        )
        assert _test("prober", ARR) == (True, "Sonarr 4.0.1")
        assert route.calls.last.request.headers["x-api-key"] == "k"

    @respx.mock
    def test_auth_error(self) -> None:
        respx.get("http://sonarr:8989/api/v3/system/status").respond(401)
        ok, message = _test("prober", ARR)
        assert not ok and "Authentication failed" in message

    @respx.mock
    def test_other_status_and_connection_error(self) -> None:
        respx.get("http://sonarr:8989/api/v3/system/status").respond(502)
        assert _test("prober", ARR) == (False, "Unexpected response: HTTP 502")
        respx.get("http://sonarr:8989/api/v3/system/status").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert _test("prober", ARR) == (False, "Connection failed: refused")

    @respx.mock
    def test_invalid_json(self) -> None:
        respx.get("http://sonarr:8989/api/v3/system/status").respond(200, text="<html>")
        ok, message = _test("prober", ARR)
        assert not ok and message.startswith("Invalid response")

    def test_validation(self) -> None:
        ok, _ = _test("prober", {"type": "radarr", "url": "radarr"})
        assert not ok


class TestMediaServers:
    @respx.mock
    def test_plex(self) -> None:
        respx.get("http://plex:32400/library/sections").respond(
            json={"MediaContainer": {"Directory": [{}, {}]}}
        )
        config = {"type": "plex", "url": "http://plex:32400", "token": "t"}
        assert _test("media_server", config) == (
            True,
            "Connected to Plex (2 libraries)",
        )
        respx.get("http://plex:32400/library/sections").respond(401)
        assert _test("media_server", config)[0] is False

    @respx.mock
    def test_jellyfin_and_emby(self) -> None:
        respx.get("http://jf:8096/System/Info").respond(
            json={"ServerName": "Home", "Version": "10.10"}
        )
        config = {"type": "jellyfin", "url": "http://jf:8096", "api_key": "k"}
        assert _test("media_server", config) == (True, "Connected to Home 10.10")
        respx.get("http://emby:8096/System/Info").respond(json={})
        emby = {"type": "emby", "url": "http://emby:8096", "api_key": "k"}
        assert _test("media_server", emby) == (True, "Connected to emby")
        respx.get("http://emby:8096/System/Info").respond(403)
        assert _test("media_server", emby)[0] is False

    def test_validation(self) -> None:
        assert _test("media_server", {"type": "plex"})[0] is False


class TestNotifications:
    def test_no_urls(self) -> None:
        assert _test("notifications", {"urls": []}) == (
            False,
            "No notification URLs configured",
        )

    def test_invalid_url(self) -> None:
        ok, message = _test("notifications", {"urls": ["nope://x"]})
        assert not ok and "invalid" in message

    def test_validation(self) -> None:
        assert _test("notifications", {"urls": 5})[0] is False

    def test_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[dict[str, Any]] = []

        def notify(self: apprise.Apprise, **kwargs: Any) -> bool:
            sent.append(kwargs)
            return len(sent) == 1

        monkeypatch.setattr(apprise.Apprise, "notify", notify)
        config = {"urls": ["json://localhost/hook"]}
        assert _test("notifications", config) == (
            True,
            "Test notification sent to 1 target(s)",
        )
        assert _test("notifications", config) == (
            False,
            "Sending failed; see the logs for details",
        )
