"""Periodic schedule trigger source."""

import asyncio
import logging
import time

from boomarr.models import ScanEvent
from boomarr.triggers.base import TriggerSource

_LOGGER = logging.getLogger(__name__)


class ScheduleTrigger(TriggerSource):
    """Emits a scan event at a fixed interval.

    Args:
        interval: Seconds between scan events.
        run_on_start: If ``True``, emit an event immediately when started
            rather than waiting for the first interval to elapse.
    """

    def __init__(self, *, interval: float, run_on_start: bool = True) -> None:
        self._interval = interval
        self._run_on_start = run_on_start
        self._task: asyncio.Task[None] | None = None

    async def start(self, queue: asyncio.Queue[ScanEvent]) -> None:
        """Spawn the periodic loop as a background task."""
        _LOGGER.info(
            "Schedule trigger started (interval=%ss, run_on_start=%s)",
            self._interval,
            self._run_on_start,
        )
        self._task = asyncio.create_task(self._loop(queue))

    async def stop(self) -> None:
        """Cancel the periodic loop if running."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            _LOGGER.debug("Schedule trigger stopped")

    async def _loop(self, queue: asyncio.Queue[ScanEvent]) -> None:
        """Emit scan events on the configured schedule."""
        if self._run_on_start:
            await self._emit(queue)
        while True:
            await asyncio.sleep(self._interval)
            await self._emit(queue)

    async def _emit(self, queue: asyncio.Queue[ScanEvent]) -> None:
        """Put a single scan event into the queue."""
        _LOGGER.debug("Schedule trigger emitting scan event")
        await queue.put(ScanEvent(source="schedule", timestamp=time.monotonic()))
