"""Tests for metrics, the scan runner, notifications and media server hooks."""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from boomarr.config import (
    Config,
    EmbyConfig,
    GeneralConfig,
    JellyfinConfig,
    LoggingConfig,
    NotificationsConfig,
    PathMapping,
    PlexConfig,
    map_to_local,
    map_to_remote,
)
from boomarr.hooks import (
    JellyfinRefreshHook,
    NotificationHook,
    PlexRefreshHook,
    build_hooks,
)
from boomarr.metrics import Metrics
from boomarr.models import ScanEvent, ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.runner import ScanReport, ScanRunner
from boomarr.server import HttpServer


def _report(**kwargs: Any) -> ScanReport:
    result = kwargs.pop("result", ScanResult())
    return ScanReport(result=result, duration=1.0, finished_at=time.time(), **kwargs)


class TestMetrics:
    def test_render_and_record(self) -> None:
        metrics = Metrics()
        result = ScanResult(created=3, removed=1, probed=2, errors=1, blocked=1)
        result.links['/out/a"b'] = 7
        metrics.record_scan(result, 2.5, cache_entries=42)
        metrics.record_scan(None, 0.1)
        text = metrics.render()
        assert 'boomarr_scans_total{status="ok"} 1' in text
        assert 'boomarr_scans_total{status="failed"} 1' in text
        assert "boomarr_links_created_total 3" in text
        assert "boomarr_removal_guard_blocked_total 1" in text
        assert 'boomarr_links{output="/out/a\\"b"} 7' in text
        assert "boomarr_cache_entries 42" in text
        assert "# TYPE boomarr_scans_total counter" in text
        assert 'boomarr_build_info{version="' in text
        assert metrics.get("boomarr_links_created_total") == 3


class TestPathMapping:
    def test_mapping_roundtrip(self) -> None:
        mappings = [
            PathMapping(local=Path("/data"), remote="/mnt/media"),
            PathMapping(local=Path("/data/filtered"), remote="/plex/filtered/"),
        ]
        assert map_to_remote(Path("/data/filtered/de"), mappings) == "/plex/filtered/de"
        assert map_to_remote(Path("/data/x"), mappings) == "/mnt/media/x"
        assert map_to_remote(Path("/other"), mappings) == "/other"
        assert map_to_remote(Path("/data"), mappings) == "/mnt/media"
        assert map_to_local("/plex/filtered/de", mappings) == Path("/data/filtered/de")
        assert map_to_local("/mnt/mediax", mappings) == Path("/mnt/mediax")


class TestNotificationHook:
    def _hook(self, **cfg: Any) -> tuple[NotificationHook, MagicMock]:
        fake = MagicMock()
        fake.add.return_value = True
        fake.notify.return_value = True
        with patch("apprise.Apprise", return_value=fake):
            hook = NotificationHook(
                NotificationsConfig.model_validate({"urls": ["json://x"], **cfg})
            )
        return hook, fake

    def test_changes_only_when_enabled(self) -> None:
        result = ScanResult(created=2)
        result.changed_outputs.add("/out/de")
        hook, fake = self._hook()
        hook.after_scan(_report(result=result))
        fake.notify.assert_not_called()

        hook, fake = self._hook(on_changes=True)
        hook.after_scan(_report(result=result))
        kwargs = fake.notify.call_args.kwargs
        assert kwargs["title"] == "Boomarr: library updated"
        assert "/out/de" in kwargs["body"]

    def test_errors_and_blocked(self) -> None:
        hook, fake = self._hook()
        hook.after_scan(_report(result=ScanResult(errors=2, blocked=1)))
        kwargs = fake.notify.call_args.kwargs
        assert kwargs["title"] == "Boomarr: attention needed"
        assert "--force" in kwargs["body"]

    def test_scan_failure(self) -> None:
        hook, fake = self._hook()
        hook.after_scan(_report(result=None, error="RuntimeError: boom"))
        assert fake.notify.call_args.kwargs["body"] == "RuntimeError: boom"

    def test_urls_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOOMARR_NOTIFY_URLS", "json://a  tgram://b/c")
        cfg = NotificationsConfig()
        assert [u.get_secret_value() for u in cfg.urls] == ["json://a", "tgram://b/c"]


class _Recorder(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict[str, str], bytes]] = []  # noqa: RUF012

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).requests.append(
            (self.command, self.path, dict(self.headers.items()), body)
        )

    def do_GET(self) -> None:
        self._record()
        if (
            self.path.startswith("/library/sections?")
            or self.path == "/library/sections"
        ):
            payload = (
                b'<MediaContainer><Directory key="3" title="Filme DE">'
                b'<Location path="/plex/filtered/movies-deu"/></Directory>'
                b'<Directory key="4" title="Other"><Location path="/plex/other"/>'
                b"</Directory></MediaContainer>"
            )
        else:
            payload = b""
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        self._record()
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def fake_server() -> Iterator[str]:
    _Recorder.requests = []
    httpd = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _changed(*outputs: str) -> ScanReport:
    result = ScanResult(created=1)
    result.changed_outputs.update(outputs)
    return _report(result=result)


class TestMediaServerHooks:
    def test_plex_refreshes_matching_section(self, fake_server: str) -> None:
        hook = PlexRefreshHook(
            PlexConfig(
                url=fake_server,
                token=SecretStr("tok"),
                path_mappings=[
                    PathMapping(local=Path("/data/filtered"), remote="/plex/filtered")
                ],
            )
        )
        hook.after_scan(_changed("/data/filtered/movies-deu", "/data/filtered/unknown"))
        paths = [r[1] for r in _Recorder.requests]
        assert paths[0] == "/library/sections"
        assert (
            paths[1]
            == "/library/sections/3/refresh?path=%2Fplex%2Ffiltered%2Fmovies-deu"
        )
        assert len(paths) == 2
        assert _Recorder.requests[0][2]["X-Plex-Token"] == "tok"

    def test_plex_nothing_changed(self, fake_server: str) -> None:
        PlexRefreshHook(PlexConfig(url=fake_server, token=SecretStr("t"))).after_scan(
            _report()
        )
        assert _Recorder.requests == []

    @pytest.mark.parametrize("cls", [JellyfinConfig, EmbyConfig])
    def test_jellyfin_media_updated(
        self, fake_server: str, cls: type[JellyfinConfig] | type[EmbyConfig]
    ) -> None:
        hook = JellyfinRefreshHook(cls(url=fake_server + "/", api_key=SecretStr("key")))
        hook.after_scan(_changed("/data/filtered/movies-deu"))
        method, path, headers, body = _Recorder.requests[0]
        assert (method, path) == ("POST", "/Library/Media/Updated")
        assert headers["X-Emby-Token"] == "key"
        assert json.loads(body) == {
            "Updates": [{"Path": "/data/filtered/movies-deu", "UpdateType": "Modified"}]
        }

    def test_invalid_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="http"):
            JellyfinConfig.model_validate({"url": "ftp://x", "api_key": "k"})

    def test_build_hooks(self) -> None:
        cfg = Config(
            config_dir=Path("."),
            config_file="t.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
            media_servers=[
                PlexConfig(url="http://plex:32400", token=SecretStr("t")),
                JellyfinConfig(url="http://jf:8096", api_key=SecretStr("k")),
            ],
        )
        hooks = build_hooks(cfg)
        assert [type(h).__name__ for h in hooks] == [
            "PlexRefreshHook",
            "JellyfinRefreshHook",
        ]


class TestScanRunner:
    def _config(self) -> Config:
        return Config(
            config_dir=Path("."),
            config_file="t.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
        )

    def test_hooks_called_and_status(self) -> None:
        hook = MagicMock()
        runner = ScanRunner(self._config(), PipelineFactory(), hooks=[hook])
        assert runner.status()["last_scan"] is None
        runner.run(threading.Event())
        hook.after_scan.assert_called_once()
        status = runner.status()
        assert status["running"] is False
        assert status["last_scan"]["result"]["created"] == 0
        json.dumps(status)

    def test_failing_hook_does_not_break_scan(self) -> None:
        hook = MagicMock()
        hook.after_scan.side_effect = RuntimeError("nope")
        runner = ScanRunner(self._config(), PipelineFactory(), hooks=[hook])
        assert runner.run(threading.Event()) == ScanResult()

    def test_hooks_skipped_when_cancelled(self) -> None:
        hook = MagicMock()
        cancel = threading.Event()
        cancel.set()
        ScanRunner(self._config(), PipelineFactory(), hooks=[hook]).run(cancel)
        hook.after_scan.assert_not_called()


def _http(port: int, request: bytes) -> tuple[int, bytes]:
    async def main() -> tuple[int, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        data = await reader.read()
        writer.close()
        head, _, body = data.partition(b"\r\n\r\n")
        return int(head.split(b" ")[1]), body

    return asyncio.run(main())


class TestServerRoutes:
    def _run(
        self, server: HttpServer, requests: list[bytes]
    ) -> list[tuple[int, bytes]]:
        results: list[tuple[int, bytes]] = []

        async def main() -> None:
            queue: asyncio.Queue[ScanEvent] = asyncio.Queue()
            await server.start(queue)
            loop = asyncio.get_running_loop()
            try:
                for raw in requests:
                    results.append(
                        await loop.run_in_executor(None, _http, server.port, raw)
                    )
            finally:
                await server.stop()

        asyncio.run(main())
        return results

    def test_metrics_and_status(self) -> None:
        server = HttpServer(
            host="127.0.0.1",
            port=0,
            api_key="k",
            status_provider=lambda: {"running": False},
        )
        (metrics, status_ok, status_denied) = self._run(
            server,
            [
                b"GET /metrics HTTP/1.1\r\n\r\n",
                b"GET /api/v1/status HTTP/1.1\r\nX-Api-Key: k\r\n\r\n",
                b"GET /api/v1/status HTTP/1.1\r\n\r\n",
            ],
        )
        assert metrics[0] == 200
        assert b"boomarr_build_info" in metrics[1]
        assert status_ok == (200, b'{"running": false}')
        assert status_denied[0] == 401

    def test_metrics_auth(self) -> None:
        server = HttpServer(host="127.0.0.1", port=0, api_key="k", metrics_auth=True)
        denied, allowed = self._run(
            server,
            [
                b"GET /metrics HTTP/1.1\r\n\r\n",
                b"GET /metrics?apikey=k HTTP/1.1\r\n\r\n",
            ],
        )
        assert denied[0] == 401
        assert allowed[0] == 200
