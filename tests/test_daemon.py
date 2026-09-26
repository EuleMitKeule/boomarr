"""Tests for boomarr.daemon (the long running ``watch`` process)."""

import asyncio
import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from boomarr import daemon as daemon_module
from boomarr.daemon import Daemon, merge_events
from boomarr.models import ScanEvent, ScanResult
from boomarr.triggers.schedule import ScheduleTrigger


def _event(source: str, *, dry_run: bool = False, force: bool = False) -> ScanEvent:
    return ScanEvent(
        source=source, timestamp=time.monotonic(), dry_run=dry_run, force=force
    )


class TestMergeEvents:
    def test_real_scan_wins_over_dry_run(self) -> None:
        merged = merge_events(
            [_event("a", dry_run=True), _event("b"), _event("b", force=True)]
        )
        assert merged.source == "b"
        assert merged.dry_run is False
        assert merged.force is True

    def test_only_dry_runs(self) -> None:
        merged = merge_events([_event("a", dry_run=True), _event("c", dry_run=True)])
        assert merged.source == "a, c"
        assert merged.dry_run is True
        assert merged.force is False


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _enable_server(daemon: Daemon, port: int, enabled: bool = True) -> None:
    server = daemon.config.server.model_copy(
        update={"enabled": enabled, "host": "127.0.0.1", "port": port}
    )
    daemon.config = daemon.config.model_copy(update={"server": server})
    daemon._server_config = server


def _disable_server(daemon: Daemon) -> None:
    _enable_server(daemon, 9797, enabled=False)


async def _run_with(daemon: Daemon, body: Callable[[], Awaitable[Any]]) -> Any:
    """Run the daemon's main loop while *body* interacts with it."""
    task = asyncio.create_task(daemon.main())
    while daemon._queue is None:
        await asyncio.sleep(0.01)
    try:
        return await body()
    finally:
        daemon.request_shutdown()
        await asyncio.wait_for(task, 10)


async def _next(queue: asyncio.Queue[dict[str, Any]], kind: str) -> dict[str, Any]:
    while True:
        event = await asyncio.wait_for(queue.get(), 10)
        if event["type"] == kind:
            return event


class TestDaemon:
    def test_initial_state(self, daemon: Daemon) -> None:
        snapshot = daemon.snapshot()
        assert snapshot["scanning"] is False
        assert snapshot["current_scan"] is None
        assert snapshot["last_scan"] is None
        assert snapshot["queued"] == 0
        assert snapshot["next_scheduled_scan"] is None
        assert daemon.shutting_down is False
        assert daemon.cancel_scan() is False
        with pytest.raises(RuntimeError, match="not running"):
            asyncio.run(daemon.request_scan("x"))

    def test_scan_runs_and_publishes_events(
        self, daemon: Daemon, tmp_path: Path
    ) -> None:
        _disable_server(daemon)
        daemon.config = daemon.config.model_copy(
            update={"watch": daemon.config.watch.model_copy(update={"debounce": 0.05})}
        )

        async def body() -> list[str]:
            async with daemon.events.subscribe() as queue:
                await daemon.request_scan("test")
                await daemon.request_scan("test", dry_run=True)
                started = await _next(queue, "scan.started")
                assert started["data"] == {
                    "source": "test",
                    "dry_run": False,
                    "force": False,
                }
                progress = await _next(queue, "scan.progress")
                finished = await _next(queue, "scan.finished")
                assert daemon.state.list_scans()[1] == 1
                return [progress["data"]["phase"], finished["data"]["source"]]

        phase, source = asyncio.run(_run_with(daemon, body))
        assert phase == "discovering"
        assert source == "test"
        snapshot = daemon.snapshot()
        assert snapshot["last_scan"]["result"]["created"] > 0
        assert list((tmp_path / "out").iterdir())

    def test_preflight_skips_scan(self, daemon: Daemon) -> None:
        _disable_server(daemon)
        daemon.skip_readonly_check = False

        async def body() -> dict[str, Any]:
            async with daemon.events.subscribe() as queue:
                await daemon.request_scan("test")
                return await _next(queue, "scan.skipped")

        event = asyncio.run(_run_with(daemon, body))
        assert "read-only" in event["data"]["reason"]

    def test_cancel_running_scan(
        self, daemon: Daemon, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _disable_server(daemon)
        seen: list[bool] = []

        def blocking_run(cancel: threading.Event, **_: Any) -> ScanResult:
            seen.append(cancel.wait(5))
            return ScanResult()

        monkeypatch.setattr(daemon.runner, "run", blocking_run)

        async def body() -> None:
            async with daemon.events.subscribe() as queue:
                await daemon.request_scan("test")
                await _next(queue, "scan.started")
                assert daemon.scanning
                assert daemon.snapshot()["current_scan"]["source"] == "test"
                assert daemon.cancel_scan() is True
                await _next(queue, "scan.finished")

        asyncio.run(_run_with(daemon, body))
        assert seen == [True]

    def test_failing_scan_keeps_daemon_alive(
        self,
        daemon: Daemon,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _disable_server(daemon)
        calls: list[int] = []

        def failing(cancel: threading.Event, **_: Any) -> ScanResult:
            calls.append(1)
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(daemon.runner, "run", failing)

        async def body() -> None:
            async with daemon.events.subscribe() as queue:
                for _ in range(2):
                    await daemon.request_scan("test")
                    await _next(queue, "scan.finished")

        with caplog.at_level(logging.ERROR):
            asyncio.run(_run_with(daemon, body))
        assert len(calls) == 2
        assert "Scan failed" in caplog.text

    def test_shutdown_during_debounce(self, daemon: Daemon) -> None:
        _disable_server(daemon)

        async def body() -> None:
            await daemon.request_scan("test")
            await asyncio.sleep(0.05)  # inside the 2 s debounce window

        asyncio.run(_run_with(daemon, body))
        assert daemon.runner.last_report is None

    def test_schedule_trigger_and_next_scan(self, daemon: Daemon) -> None:
        _disable_server(daemon)
        from boomarr.config import ScheduleTriggerConfig

        daemon.config = daemon.config.model_copy(
            update={
                "triggers": [ScheduleTriggerConfig(interval=3600, run_on_start=False)]
            }
        )

        async def body() -> float | None:
            await asyncio.sleep(0.05)
            assert isinstance(daemon.triggers[0], ScheduleTrigger)
            return daemon.next_scheduled_scan()

        next_scan = asyncio.run(_run_with(daemon, body))
        assert next_scan is not None and next_scan > time.time()

    def test_apply_config(
        self, daemon: Daemon, config_store: Any, tmp_path: Path
    ) -> None:
        _disable_server(daemon)
        doc = config_store.document()["config"]
        doc["database"] = {"type": "memory"}
        doc["logging"]["level"] = "DEBUG"
        doc["triggers"] = [{"type": "schedule", "interval": 60, "run_on_start": False}]
        doc["server"]["port"] = 1234
        new = config_store.validate(doc)

        async def body() -> bool:
            async with daemon.events.subscribe() as queue:
                restart = await daemon.apply_config(new)
                event = await _next(queue, "config.updated")
                assert event["data"] == {"restart_required": restart}
                return restart

        assert asyncio.run(_run_with(daemon, body)) is True
        assert daemon.restart_required is True
        assert daemon.config is new
        assert len(daemon.triggers) == 1
        assert daemon.snapshot()["restart_required"] is True

    def test_apply_config_while_stopped(
        self, daemon: Daemon, config_store: Any
    ) -> None:
        new = config_store.validate(config_store.document()["config"])
        assert asyncio.run(daemon.apply_config(new)) is False
        assert daemon.triggers == []

    def test_apply_config_database_while_scanning(
        self, daemon: Daemon, config_store: Any
    ) -> None:
        old_state = daemon.state
        daemon.scan_started_at = time.time()
        doc = config_store.document()["config"]
        doc["database"] = {"type": "memory"}
        asyncio.run(daemon.apply_config(config_store.validate(doc)))
        assert daemon.state is not old_state
        old_state.get_stats()  # still open for the running scan
        old_state.close()

    def test_heartbeat(
        self, daemon: Daemon, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _disable_server(daemon)
        blocker = tmp_path / "file"
        blocker.write_text("")
        daemon._heartbeat_file = blocker / "hb"  # parent is a file: fails
        daemon._heartbeat_interval = 0.01

        async def body() -> None:
            await asyncio.sleep(0.1)

        with caplog.at_level(logging.WARNING):
            asyncio.run(_run_with(daemon, body))
        assert caplog.text.count("Cannot write heartbeat") == 1

        daemon._heartbeat_file = tmp_path / "sub" / "hb"
        daemon._shutdown.clear()
        asyncio.run(_run_with(daemon, body))
        assert (tmp_path / "sub" / "hb").exists()

    def test_web_server(self, daemon: Daemon) -> None:
        port = _free_port()
        _enable_server(daemon, port)

        async def body() -> int:
            for _ in range(200):
                if daemon._server is not None and daemon._server.started:
                    break
                await asyncio.sleep(0.02)
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{port}/health")
            return response.status_code

        assert asyncio.run(_run_with(daemon, body)) == 200

    def test_web_server_port_in_use(
        self, daemon: Daemon, caplog: pytest.LogCaptureFixture
    ) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            _enable_server(daemon, int(sock.getsockname()[1]))

            async def main() -> None:
                await asyncio.wait_for(daemon.main(), 10)

            with caplog.at_level(logging.CRITICAL):
                asyncio.run(main())
        assert "Cannot listen" in caplog.text

    def test_run_handles_keyboard_interrupt(
        self, daemon: Daemon, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def interrupt(coro: Any) -> None:
            coro.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(daemon_module.asyncio, "run", interrupt)
        daemon.run()

    def test_run_until_signal(self, daemon: Daemon) -> None:
        _disable_server(daemon)
        timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM))
        timer.start()
        daemon.run()
        timer.join()
        assert daemon.shutting_down
