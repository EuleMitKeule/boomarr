"""The long-running ``boomarr watch`` process.

Owns everything that lives longer than one scan: the trigger sources, the
debounced scan queue, the web server, live events and the log buffer. The
configuration can be replaced at runtime (saved from the web UI) without a
restart; only listener settings of the web server need one.
"""

import asyncio
import contextlib
import logging
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from boomarr.auth_store import AuthStore
from boomarr.config import Config, ServerConfig
from boomarr.config_store import ConfigStore
from boomarr.const import HEARTBEAT_INTERVAL, VERSION
from boomarr.events import EventBus, LogBuffer
from boomarr.health import preflight
from boomarr.hooks import build_hooks
from boomarr.log import setup_logging
from boomarr.models import ScanEvent, ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.runner import ScanRunner
from boomarr.state import StateStore
from boomarr.triggers.base import TriggerSource
from boomarr.triggers.schedule import ScheduleTrigger

if TYPE_CHECKING:  # pragma: no cover
    import uvicorn

_LOGGER = logging.getLogger(__name__)

_RESTART_FIELDS = ("enabled", "host", "port", "url_base", "trusted_proxies")


def merge_events(events: list[ScanEvent]) -> ScanEvent:
    """Collapse debounced events into the single scan that will run.

    Any real (non dry-run) request wins over dry runs; ``force`` is kept if
    any of the merged requests asked for it.
    """
    real = [e for e in events if not e.dry_run]
    chosen = real or events
    sources = list(dict.fromkeys(e.source for e in chosen))
    return ScanEvent(
        source=", ".join(sources),
        timestamp=chosen[0].timestamp,
        dry_run=not real,
        force=any(e.force for e in chosen),
    )


class Daemon:
    """Coordinates triggers, scans, the web server and configuration reloads."""

    def __init__(
        self,
        store: ConfigStore,
        auth: AuthStore,
        *,
        heartbeat_file: Path | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        skip_readonly_check: bool = False,
    ) -> None:
        self.store = store
        self.auth = auth
        self.config: Config = store.config or store.load()
        self.skip_readonly_check = skip_readonly_check
        self.events = EventBus()
        self.logs = LogBuffer(self.events)
        self.started_at = time.time()
        self.restart_required = False
        self.progress: dict[str, Any] | None = None
        self.scan_started_at: float | None = None
        self.current_scan: ScanEvent | None = None
        self._heartbeat_file = heartbeat_file
        self._heartbeat_interval = heartbeat_interval
        self._server_config: ServerConfig = self.config.server
        self.state: StateStore = PipelineFactory.build_state_store(self.config)
        self.runner = self._build_runner(self.config)
        self.triggers: list[TriggerSource] = []
        self._queue: asyncio.Queue[ScanEvent] | None = None
        self._shutdown = asyncio.Event()
        self._cancel_scan = threading.Event()
        self._server: uvicorn.Server | None = None
        self._install_log_buffer()

    # -- construction helpers ---------------------------------------------

    def _install_log_buffer(self) -> None:
        setup_logging(
            self.config.logging, tz=self.config.general.tz, extra_handlers=[self.logs]
        )

    def _build_runner(self, config: Config) -> ScanRunner:
        factory = PipelineFactory(state=self.state)
        return ScanRunner(config, factory, hooks=build_hooks(config))

    @staticmethod
    def build_triggers(config: Config) -> list[TriggerSource]:
        return PipelineFactory.build_triggers(config.triggers)

    # -- public API (used by the web layer) --------------------------------

    @property
    def scanning(self) -> bool:
        return self.scan_started_at is not None

    @property
    def shutting_down(self) -> bool:
        return self._shutdown.is_set()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    def next_scheduled_scan(self) -> float | None:
        times = [
            t.next_fire_at
            for t in self.triggers
            if isinstance(t, ScheduleTrigger) and t.next_fire_at is not None
        ]
        return min(times) if times else None

    async def request_scan(
        self, source: str, *, dry_run: bool = False, force: bool = False
    ) -> None:
        """Queue a scan (debounced together with other pending requests)."""
        if self._queue is None:
            raise RuntimeError("The daemon is not running")
        await self._queue.put(
            ScanEvent(
                source=source, timestamp=time.monotonic(), dry_run=dry_run, force=force
            )
        )
        self.events.publish("scan.queued", {"source": source, "dry_run": dry_run})

    def cancel_scan(self) -> bool:
        """Ask a running scan to stop; returns False if none is running."""
        if not self.scanning:
            return False
        self._cancel_scan.set()
        return True

    async def apply_config(self, config: Config) -> bool:
        """Switch to *config* without a restart.

        Returns True if listener settings of the web server changed and only
        take effect after a restart.
        """
        old = self.config
        self.config = config
        if config.database != old.database:
            old_state = self.state
            self.state = PipelineFactory.build_state_store(config)
            if not self.scanning:
                old_state.close()
        if config.logging != old.logging or config.general.tz != old.general.tz:
            self._install_log_buffer()
        self.runner = self._build_runner(config)
        if config.triggers != old.triggers and self._queue is not None:
            await self._stop_triggers()
            self.triggers = self.build_triggers(config)
            await self._start_triggers()
        restart = any(
            getattr(config.server, name) != getattr(self._server_config, name)
            for name in _RESTART_FIELDS
        )
        self.restart_required = restart
        self.events.publish("config.updated", {"restart_required": restart})
        _LOGGER.info(
            "Configuration applied%s",
            " (restart required for server settings)" if restart else "",
        )
        return restart

    def snapshot(self) -> dict[str, Any]:
        """Runtime state for the dashboard."""
        last = self.runner.last_report
        return {
            "version": VERSION,
            "started_at": self.started_at,
            "scanning": self.scanning,
            "scan_started_at": self.scan_started_at,
            "current_scan": (
                {
                    "source": self.current_scan.source,
                    "dry_run": self.current_scan.dry_run,
                    "force": self.current_scan.force,
                }
                if self.current_scan
                else None
            ),
            "progress": self.progress,
            "queued": self.queue_size,
            "next_scheduled_scan": self.next_scheduled_scan(),
            "restart_required": self.restart_required,
            "last_scan": last.as_dict() if last else None,
        }

    def request_shutdown(self) -> None:
        _LOGGER.info("Shutdown requested")
        self._shutdown.set()
        self._cancel_scan.set()
        if self._server is not None:
            self._server.should_exit = True

    # -- main loop --------------------------------------------------------

    def run(self) -> None:
        """Run until SIGTERM/SIGINT (blocking)."""
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(self.main())

    async def main(self) -> None:
        loop = asyncio.get_running_loop()
        self.events.bind(loop)
        self._queue = asyncio.Queue()
        if sys.platform != "win32":  # pragma: no branch
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self.request_shutdown)
        tasks: list[asyncio.Task[Any]] = [asyncio.create_task(self._heartbeat())]
        try:
            if self._server_config.enabled:
                tasks.append(asyncio.create_task(self._serve()))
            self.triggers = self.build_triggers(self.config)
            await self._start_triggers()
            await self._worker()
        finally:
            await self._stop_triggers()
            self.request_shutdown()
            for task in tasks:
                if task.done():
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if sys.platform != "win32":  # pragma: no branch
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
            self.state.close()

    async def _start_triggers(self) -> None:
        assert self._queue is not None  # noqa: S101 - set in main()
        for trigger in self.triggers:
            await trigger.start(self._queue)

    async def _stop_triggers(self) -> None:
        for trigger in self.triggers:
            await trigger.stop()

    async def _serve(self) -> None:
        import uvicorn

        from boomarr.web.app import create_app

        cfg = self._server_config
        try:
            sock = socket.create_server(
                (cfg.host, cfg.port),
                family=socket.AF_INET6 if ":" in cfg.host else socket.AF_INET,
                reuse_port=False,
            )
        except OSError as exc:
            _LOGGER.critical("Cannot listen on %s:%d: %s", cfg.host, cfg.port, exc)
            self.request_shutdown()
            return
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(self),
                proxy_headers=False,  # handled by ProxyHeadersMiddleware
                log_level="warning",
                timeout_graceful_shutdown=3,
                access_log=False,
                lifespan="off",
            )
        )
        server.capture_signals = contextlib.nullcontext  # ty: ignore[invalid-assignment]
        self._server = server
        _LOGGER.info(
            "Web UI listening on http://%s:%d%s/", cfg.host, cfg.port, cfg.url_base
        )
        try:
            await server.serve(sockets=[sock])
        finally:
            sock.close()

    async def _heartbeat(self) -> None:
        if self._heartbeat_file is None:
            return
        warned = False
        while True:
            try:
                self._heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
                self._heartbeat_file.touch()
            except OSError as exc:
                if not warned:
                    _LOGGER.warning(
                        "Cannot write heartbeat file '%s': %s",
                        self._heartbeat_file,
                        exc,
                    )
                    warned = True
            await asyncio.sleep(self._heartbeat_interval)

    async def _next_event(self) -> ScanEvent | None:
        assert self._queue is not None  # noqa: S101 - set in main()
        while not self._shutdown.is_set():
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
        return None

    async def _collect(self, first: ScanEvent) -> list[ScanEvent]:
        assert self._queue is not None  # noqa: S101 - set in main()
        events = [first]
        deadline = time.monotonic() + self.config.watch.debounce
        while True:
            remaining = max(deadline - time.monotonic(), 0)
            try:
                events.append(await asyncio.wait_for(self._queue.get(), remaining))
            except TimeoutError:
                return events

    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self._next_event()
            if first is None:
                break
            event = merge_events(await self._collect(first))
            if self._shutdown.is_set():
                break
            reason = preflight(
                self.config, skip_readonly_check=self.skip_readonly_check
            )
            if reason is not None:
                _LOGGER.error("Scan skipped: %s", reason)
                self.events.publish("scan.skipped", {"reason": reason})
                continue
            await self._run_scan(loop, event)

    async def _run_scan(
        self, loop: asyncio.AbstractEventLoop, event: ScanEvent
    ) -> None:
        self._cancel_scan.clear()
        self.current_scan = event
        self.scan_started_at = time.time()
        self.progress = None
        self.events.publish(
            "scan.started",
            {"source": event.source, "dry_run": event.dry_run, "force": event.force},
        )
        runner = self.runner
        _LOGGER.info(
            "Starting %s (trigger: %s)",
            "dry run" if event.dry_run else "scan",
            event.source,
        )

        def on_progress(progress: dict[str, Any]) -> None:
            self.progress = progress
            self.events.publish("scan.progress", progress)

        result: ScanResult | None = None
        try:
            result = await loop.run_in_executor(
                None,
                lambda: runner.run(
                    self._cancel_scan,
                    dry_run=event.dry_run,
                    force=event.force,
                    source=event.source,
                    on_progress=on_progress,
                ),
            )
        except Exception:
            # A failing scan must never take the daemon down.
            _LOGGER.exception("Scan failed, will retry on the next trigger")
        finally:
            self.scan_started_at = None
            self.current_scan = None
            self.progress = None
            report = runner.last_report
            self.events.publish("scan.finished", report.as_dict() if report else None)
        if result is not None:
            _LOGGER.info(
                "Scan complete: %d created, %d removed, %d unchanged, %d probed, "
                "%d skipped, %d errors",
                result.created,
                result.removed,
                result.unchanged,
                result.probed,
                result.skipped,
                result.errors,
            )
