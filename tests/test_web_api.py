"""Tests for the REST API used by the web UI and the SPA serving."""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from boomarr.config_store import SECRET_PREFIX
from boomarr.const import AuthMethod
from boomarr.daemon import Daemon
from boomarr.web import app as app_module
from boomarr.web.routes import api as api_module


def _queue(daemon: Daemon) -> asyncio.Queue[Any]:
    assert daemon._queue is not None
    return daemon._queue


# ---------------------------------------------------------------------------
# System, dashboard, languages
# ---------------------------------------------------------------------------


class TestSystem:
    def test_status(self, admin: TestClient, web_daemon: Daemon) -> None:
        data = admin.get("/api/v1/system/status").json()
        assert data["config_file"] == str(web_daemon.store.path)
        assert data["config_writable"] is True
        assert data["database"].endswith("boomarr.db")
        assert data["log_file"] is None
        assert data["user"] == {"name": "admin", "method": "session"}

    def test_status_memory_database_and_log_file(
        self, admin: TestClient, web_daemon: Daemon, tmp_path: Path
    ) -> None:
        from boomarr.config import MemoryDatabaseConfig

        logging_cfg = web_daemon.config.logging.model_copy(update={"dir": tmp_path})
        web_daemon.config = web_daemon.config.model_copy(
            update={"database": MemoryDatabaseConfig(), "logging": logging_cfg}
        )
        data = admin.get("/api/v1/system/status").json()
        assert data["database"] == "memory"
        assert data["log_file"] == str(tmp_path / "boomarr.log")

    def test_health(self, admin: TestClient) -> None:
        checks = admin.get("/api/v1/system/health").json()
        assert checks[0]["id"] == "library:Movies:readonly"

    def test_dashboard(self, admin: TestClient) -> None:
        data = admin.get("/api/v1/dashboard").json()
        assert data["scanning"] is False
        assert data["libraries"][0]["name"] == "Movies"
        assert "cache" in data

    def test_dashboard_last_scan_from_older_version(
        self, admin: TestClient, web_daemon: Daemon
    ) -> None:
        # Boomarr 1.x stored the last scan without source/dry_run/...
        web_daemon.state.set_meta(
            "last_scan", {"finished_at": 1.0, "duration_seconds": 2}
        )
        last = admin.get("/api/v1/dashboard").json()["last_scan"]
        assert last["source"] == "unknown"
        assert last["dry_run"] is False
        assert last["finished_at"] == 1.0

    def test_dashboard_prefers_current_report(
        self, admin: TestClient, web_daemon: Daemon
    ) -> None:
        import threading

        web_daemon.state.set_meta("last_scan", {"finished_at": 1.0, "source": "old"})
        web_daemon.runner.run(threading.Event(), source="fresh")
        assert admin.get("/api/v1/dashboard").json()["last_scan"]["source"] == "fresh"

    def test_languages(self, admin: TestClient) -> None:
        languages = admin.get("/api/v1/languages").json()
        assert {"code": "deu", "name": "German", "code1": "de"} in languages


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class TestScans:
    def test_queue_and_cancel(self, admin: TestClient, web_daemon: Daemon) -> None:
        assert admin.post("/api/v1/scans", json={"dry_run": True}).status_code == 202
        assert admin.post("/api/v1/scans").status_code == 202
        assert web_daemon.queue_size == 2
        event = _queue(web_daemon).get_nowait()
        assert event.source == "ui:admin"
        assert event.dry_run is True
        assert admin.post("/api/v1/scans/cancel").json() == {"cancelled": False}

    def test_queue_with_api_key(self, client: TestClient, web_daemon: Daemon) -> None:
        headers = {"X-Api-Key": web_daemon.auth.api_key}
        assert client.post("/api/v1/scans", headers=headers).status_code == 202
        assert _queue(web_daemon).get_nowait().source == "api"

    def test_history(self, admin: TestClient, web_daemon: Daemon) -> None:
        for i in range(3):
            web_daemon.state.add_scan(
                {"source": f"s{i}", "result": {"changes": [{"a": 1}]}}
            )
        page = admin.get("/api/v1/scans", params={"limit": 2}).json()
        assert page["total"] == 3
        assert [s["source"] for s in page["items"]] == ["s2", "s1"]
        assert "changes" not in page["items"][0]["result"]
        scan_id = page["items"][0]["id"]
        detail = admin.get(f"/api/v1/scans/{scan_id}").json()
        assert detail["result"]["changes"] == [{"a": 1}]
        assert admin.get("/api/v1/scans/999").status_code == 404
        assert admin.get("/api/v1/scans", params={"limit": 0}).status_code == 422


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfig:
    def test_get_and_save(self, admin: TestClient, web_daemon: Daemon) -> None:
        doc = admin.get("/api/v1/config").json()
        doc["config"]["probe_workers"] = 9
        response = admin.put(
            "/api/v1/config",
            json={"config": doc["config"]},
            headers={"If-Match": f'"{doc["etag"]}"'},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["restart_required"] is False
        assert body["config"]["probe_workers"] == 9
        assert web_daemon.config.probe_workers == 9
        on_disk = yaml.safe_load(web_daemon.store.path.read_text())
        assert on_disk["probe_workers"] == 9

    def test_save_conflict(self, admin: TestClient) -> None:
        doc = admin.get("/api/v1/config").json()
        response = admin.put(
            "/api/v1/config",
            json={"config": doc["config"]},
            headers={"If-Match": "old"},
        )
        assert response.status_code == 409

    def test_save_invalid(self, admin: TestClient) -> None:
        doc = admin.get("/api/v1/config").json()
        doc["config"]["libraries"][0]["symlink_libraries"][0]["filters"][0][
            "languages"
        ] = []
        response = admin.put("/api/v1/config", json={"config": doc["config"]})
        assert response.status_code == 422
        errors = response.json()["errors"]
        assert errors[0]["loc"] == [
            "libraries",
            0,
            "symlink_libraries",
            0,
            "filters",
            0,
            "languages",
        ]
        assert errors[0]["msg"] == "At least one language is required"

    def test_save_read_only(
        self, admin: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc = admin.get("/api/v1/config").json()
        monkeypatch.setattr(os, "access", lambda *_: False)
        response = admin.put("/api/v1/config", json={"config": doc["config"]})
        assert response.status_code == 403

    def test_validate(self, admin: TestClient) -> None:
        doc = admin.get("/api/v1/config").json()["config"]
        assert admin.post("/api/v1/config/validate", json={"config": doc}).json() == {
            "valid": True,
            "warnings": [],
        }
        doc["probe_workers"] = 0
        response = admin.post("/api/v1/config/validate", json={"config": doc})
        assert response.status_code == 422

    def test_secrets_are_masked(self, admin: TestClient, web_daemon: Daemon) -> None:
        path = web_daemon.store.path
        path.write_text(
            path.read_text() + "notifications:\n  urls: ['json://secret-host']\n"
        )
        web_daemon.store.load()
        text = admin.get("/api/v1/config").text
        assert "secret-host" not in text
        assert SECRET_PREFIX in text

    def test_export_import(self, admin: TestClient, web_daemon: Daemon) -> None:
        exported = admin.get("/api/v1/config/export")
        assert (
            exported.headers["content-disposition"]
            == 'attachment; filename="boomarr.yml"'
        )
        text = exported.text.replace("name: Movies", "name: Films")
        response = admin.post(
            "/api/v1/config/import",
            content=text,
            headers={"Content-Type": "application/yaml"},
        )
        assert response.status_code == 200
        assert web_daemon.config.libraries[0].name == "Films"

    def test_export_missing_file(self, admin: TestClient, web_daemon: Daemon) -> None:
        web_daemon.store.path.unlink()
        assert admin.get("/api/v1/config/export").text == ""

    def test_import_errors(
        self, admin: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert admin.post("/api/v1/config/import", content="a: [").status_code == 422
        big = "#" * (1024 * 1024 + 1)
        assert admin.post("/api/v1/config/import", content=big).status_code == 413
        monkeypatch.setattr(os, "access", lambda *_: False)
        assert (
            admin.post(
                "/api/v1/config/import", content="probe_workers: 2\n"
            ).status_code
            == 403
        )


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------


class TestFilesystem:
    def test_list(self, admin: TestClient, tmp_path: Path) -> None:
        (tmp_path / "b").mkdir()
        (tmp_path / "A").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "file.txt").write_text("")
        data = admin.get("/api/v1/filesystem", params={"path": str(tmp_path)}).json()
        names = [e["name"] for e in data["entries"]]
        assert names[:2] == ["A", "b"]
        assert ".hidden" not in names and "file.txt" not in names
        assert data["parent"] == str(tmp_path.parent)
        assert data["writable"] is True

    def test_root_and_errors(self, admin: TestClient, tmp_path: Path) -> None:
        assert admin.get("/api/v1/filesystem").json()["parent"] is None
        assert (
            admin.get("/api/v1/filesystem", params={"path": "relative"}).status_code
            == 400
        )
        missing = admin.get(
            "/api/v1/filesystem", params={"path": str(tmp_path / "nope")}
        )
        assert missing.status_code == 400

    def test_broken_entry_is_skipped(
        self, admin: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "browse"
        (root / "dir").mkdir(parents=True)

        class Broken:
            name = "broken"
            path = str(root / "broken")

            def is_dir(self) -> bool:
                raise OSError("gone")

        real_scandir = os.scandir

        class Wrapper:
            def __init__(self, path: Any) -> None:
                self._it = real_scandir(path)

            def __enter__(self) -> Any:
                return [*self._it, Broken()]

            def __exit__(self, *args: object) -> None:
                self._it.close()

        monkeypatch.setattr(api_module.os, "scandir", Wrapper)
        data = admin.get("/api/v1/filesystem", params={"path": str(root)}).json()
        assert [e["name"] for e in data["entries"]] == ["dir"]


class TestConnectionTest:
    def test_unknown_kind(self, admin: TestClient) -> None:
        response = admin.post("/api/v1/test", json={"kind": "nope", "config": {}})
        assert response.json() == {"ok": False, "message": "Unknown test 'nope'"}

    def test_unknown_secret(self, admin: TestClient) -> None:
        response = admin.post(
            "/api/v1/test",
            json={"kind": "prober", "config": {"api_key": f"{SECRET_PREFIX}x"}},
        )
        assert response.json()["ok"] is False
        assert "secret" in response.json()["message"]


# ---------------------------------------------------------------------------
# Logs and events
# ---------------------------------------------------------------------------


class TestLogs:
    def test_logs(self, admin: TestClient, web_daemon: Daemon) -> None:
        import logging

        logging.getLogger("boomarr.test").warning("hello from the test")
        entries = admin.get("/api/v1/logs", params={"level": "WARNING"}).json()
        assert entries[-1]["message"] == "hello from the test"
        text = admin.get("/api/v1/logs/download").text
        assert "WARNING  boomarr.test: hello from the test" in text


class _FakeRequest:
    def __init__(self, disconnect_after: int) -> None:
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > self.disconnect_after


class TestEvents:
    def test_stream_until_shutdown(self, admin: TestClient, web_daemon: Daemon) -> None:
        web_daemon._shutdown.set()
        with admin.stream("GET", "/api/v1/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        assert body.startswith("retry: 3000")
        assert "event: hello" in body

    def test_stream_events_and_keepalive(
        self, web_daemon: Daemon, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api_module, "_SSE_KEEPALIVE", 0.05)

        async def main() -> list[str]:
            web_daemon.events.bind(asyncio.get_running_loop())
            request = _FakeRequest(disconnect_after=2)
            stream = api_module._event_stream(web_daemon, request)  # ty: ignore[invalid-argument-type]
            chunks = [await anext(stream), await anext(stream)]
            web_daemon.events.publish("scan.queued", {"source": "x"})
            chunks.append(await anext(stream))
            chunks.append(await anext(stream))  # keep-alive
            chunks.extend([chunk async for chunk in stream])
            return chunks

        chunks = asyncio.run(main())
        assert "event: scan.queued" in chunks[2]
        assert chunks[3] == ": keep-alive\n\n"


# ---------------------------------------------------------------------------
# Legacy endpoints
# ---------------------------------------------------------------------------


class TestLegacy:
    def test_health_is_public(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.head("/health").status_code == 200

    def test_metrics(self, client: TestClient, web_daemon: Daemon) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "boomarr_build_info" in response.text
        server = web_daemon.config.server.model_copy(update={"metrics_auth": True})
        web_daemon.config = web_daemon.config.model_copy(update={"server": server})
        assert client.get("/metrics").status_code == 401
        key = web_daemon.auth.api_key
        assert client.get("/metrics", params={"apikey": key}).status_code == 200

    def test_status_and_scan(self, client: TestClient, web_daemon: Daemon) -> None:
        headers = {"X-Api-Key": web_daemon.auth.api_key}
        status = client.get("/api/v1/status", headers=headers).json()
        assert status["running"] is False
        assert client.post("/api/v1/scan", headers=headers).json() == {
            "status": "scan queued"
        }
        assert client.post("/api/v1/webhook/radarr", headers=headers).status_code == 202
        sources = [_queue(web_daemon).get_nowait().source for _ in range(2)]
        assert sources == ["api", "webhook:radarr"]


# ---------------------------------------------------------------------------
# Single page app
# ---------------------------------------------------------------------------


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text(
        '<html><head><base href="/" /></head><body>app</body></html>'
    )
    (directory / "assets" / "app.js").write_text("console.log(1)")
    (directory / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(app_module, "DIST_DIR", directory)
    return directory


def _with_url_base(daemon: Daemon, url_base: str) -> None:
    server = daemon.config.server.model_copy(update={"url_base": url_base})
    daemon.config = daemon.config.model_copy(update={"server": server})


class TestSpa:
    def test_missing_build(
        self,
        make_client: Callable[..., TestClient],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(app_module, "DIST_DIR", tmp_path / "missing")
        response = make_client().get("/settings")
        assert "has not been built" in response.text

    def test_index_assets_and_security_headers(
        self, dist: Path, make_client: Callable[..., TestClient]
    ) -> None:
        client = make_client()
        page = client.get("/libraries/0")
        assert page.status_code == 200
        assert '<base href="/" />' in page.text
        assert page.headers["cache-control"] == "no-cache"
        assert "default-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["x-content-type-options"] == "nosniff"
        asset = client.get("/assets/app.js")
        assert asset.text == "console.log(1)"
        assert "immutable" in asset.headers["cache-control"]
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/index.html").text == page.text
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/assets/..%2F..%2Fsecret").status_code == 404
        assert client.get("/api/v1/nope").status_code == 404

    def test_url_base(
        self, dist: Path, web_daemon: Daemon, make_client: Callable[..., TestClient]
    ) -> None:
        _with_url_base(web_daemon, "/boomarr")
        client = make_client()
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"] == "/boomarr/"
        page = client.get("/boomarr/activity")
        assert '<base href="/boomarr/" />' in page.text
        assert client.get("/boomarr/health").status_code == 200

    def test_session_cookie_path_follows_url_base(
        self, web_daemon: Daemon, make_client: Callable[..., TestClient]
    ) -> None:
        _with_url_base(web_daemon, "/boomarr")
        auth = web_daemon.config.auth.model_copy(update={"method": AuthMethod.FORMS})
        web_daemon.config = web_daemon.config.model_copy(update={"auth": auth})
        web_daemon.auth.set_credentials("admin", "password1")
        client = make_client()
        response = client.post(
            "/boomarr/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert "Path=/boomarr" in response.headers["set-cookie"]

    def test_proxy_headers(
        self, dist: Path, web_daemon: Daemon, make_client: Callable[..., TestClient]
    ) -> None:
        server = web_daemon.config.server.model_copy(
            update={"trusted_proxies": ["192.168.0.0/16"]}
        )
        web_daemon.config = web_daemon.config.model_copy(update={"server": server})
        web_daemon.auth.set_credentials("admin", "password1")
        client = make_client(("192.168.1.2", 1))
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "8.8.8.8, 192.168.1.3",
            },
        )
        assert "Secure" in response.headers["set-cookie"]
