"""Watch-mode coordinator.

Manages trigger sources, a shared event queue, debouncing of rapid
duplicate events, and the scan worker loop.  Handles graceful shutdown
on SIGTERM/SIGINT.
"""

import asyncio
import logging
import signal
import sys
import time
from collections.abc import Callable

from boomarr.const import DEFAULT_WATCH_DEBOUNCE
from boomarr.models import ScanEvent, ScanResult
from boomarr.triggers.base import TriggerSource

_LOGGER = logging.getLogger(__name__)


class Watcher:
    """Coordinates trigger sources and debounced scan execution.

    All configured ``TriggerSource`` instances feed ``ScanEvent`` objects
    into a single ``asyncio.Queue``.  A worker coroutine drains the queue,
    debounces rapid duplicates, and invokes the *scan_callback* to perform
    a full library rescan.

    Args:
        triggers: Trigger sources to start.
        scan_callback: Synchronous callable that runs the full scan and
            returns a ``ScanResult``.
        debounce_seconds: Minimum quiet period before a queued event is
            acted upon.  Additional events arriving within this window
            are collapsed into a single scan.
    """

    def __init__(
        self,
        triggers: list[TriggerSource],
        scan_callback: Callable[[], ScanResult],
        *,
        debounce_seconds: float = DEFAULT_WATCH_DEBOUNCE,
    ) -> None:
        self._triggers = triggers
        self._scan_callback = scan_callback
        self._debounce_seconds = debounce_seconds
        self._queue: asyncio.Queue[ScanEvent] = asyncio.Queue()
        self._shutdown_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the watcher (blocking).

        Sets up signal handlers, starts all trigger sources, and enters
        the worker loop.  Returns when shutdown is requested or an
        unrecoverable error occurs.
        """
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            _LOGGER.info("Interrupted")

    # ------------------------------------------------------------------
    # Internal async machinery
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Main async entry point."""
        loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown (Unix only).
        # On Windows, Ctrl+C raises KeyboardInterrupt which is caught
        # in run().
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._request_shutdown)

        _LOGGER.info(
            "Starting %d trigger source(s), debounce=%.1fs",
            len(self._triggers),
            self._debounce_seconds,
        )

        for trigger in self._triggers:
            await trigger.start(self._queue)

        try:
            await self._worker()
        finally:
            _LOGGER.info("Stopping trigger sources")
            for trigger in self._triggers:
                await trigger.stop()

            if sys.platform != "win32":
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)

    async def _worker(self) -> None:
        """Process events from the queue with debouncing.

        1. Block until the first event arrives.
        2. Drain any additional events that arrive within the debounce
           window (they are collapsed into the same scan).
        3. Execute the scan callback in a thread executor so the event
           loop stays responsive for signal handling.
        4. Repeat.
        """
        while not self._shutdown_event.is_set():
            # Wait for the next event (with periodic wake-up to check
            # the shutdown flag).
            event = await self._wait_for_event()
            if event is None:
                continue

            _LOGGER.debug("Received event from '%s', debouncing…", event.source)

            # Debounce: keep draining for *debounce_seconds*.
            debounced = await self._drain_during_debounce()

            if self._shutdown_event.is_set():
                break

            if debounced:
                _LOGGER.debug("Debounced %d additional event(s)", debounced)

            _LOGGER.info("Triggering full rescan")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._scan_callback)
            _LOGGER.info(
                "Scan complete: %d created, %d removed, %d unchanged, "
                "%d skipped, %d errors",
                result.created,
                result.removed,
                result.unchanged,
                result.skipped,
                result.errors,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _wait_for_event(self) -> ScanEvent | None:
        """Block until an event arrives or the shutdown flag is set."""
        while not self._shutdown_event.is_set():
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
        return None

    async def _drain_during_debounce(self) -> int:
        """Drain all events arriving within the debounce window.

        Returns the number of extra events that were collapsed.
        """
        drained = 0
        deadline = time.monotonic() + self._debounce_seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._queue.get(), timeout=remaining)
                drained += 1
            except asyncio.TimeoutError:
                break
        return drained

    def _request_shutdown(self) -> None:
        """Signal the worker to exit after the current scan."""
        _LOGGER.info("Shutdown signal received")
        self._shutdown_event.set()
