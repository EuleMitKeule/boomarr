"""Live events for the web UI (server-sent events) and an in-memory log view."""

import asyncio
import contextlib
import itertools
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

_SUBSCRIBER_QUEUE_SIZE = 256


class EventBus:
    """Fan-out of events to any number of async subscribers.

    ``publish`` may be called from any thread (scans run in worker threads);
    delivery happens on the event loop the bus is bound to. Slow subscribers
    lose events instead of blocking publishers.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ids = itertools.count(1)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event_type: str, data: Any = None) -> None:
        event = {
            "id": next(self._ids),
            "type": event_type,
            "time": time.time(),
            "data": data,
        }
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
        else:
            with contextlib.suppress(RuntimeError):  # loop shutting down
                loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(_SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


class LogBuffer(logging.Handler):
    """Keeps the most recent log records for the UI and streams new ones."""

    def __init__(self, bus: EventBus | None = None, capacity: int = 2000) -> None:
        super().__init__(level=logging.DEBUG)
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._bus = bus
        self._ids = itertools.count(1)
        self._lock_records = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info[0] is not None:
                message = (
                    f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
                )
            entry = {
                "id": next(self._ids),
                "time": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
        except Exception:  # pragma: no cover - never break logging
            self.handleError(record)
            return
        with self._lock_records:
            self._records.append(entry)
        if self._bus is not None:
            self._bus.publish("log", entry)

    def entries(
        self, *, limit: int = 500, min_level: str = "DEBUG"
    ) -> list[dict[str, Any]]:
        levels = logging.getLevelNamesMapping()
        threshold = levels.get(min_level.upper(), logging.DEBUG)
        with self._lock_records:
            records = [
                r for r in self._records if levels.get(r["level"], 0) >= threshold
            ]
        return records[-limit:]
