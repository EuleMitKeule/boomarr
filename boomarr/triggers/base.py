"""Abstract base class for trigger sources."""

import abc
import asyncio

from boomarr.models import ScanEvent


class TriggerSource(abc.ABC):
    """Produces scan events that trigger library rescans.

    Subclasses implement the scheduling/detection logic (e.g. periodic timer,
    filesystem watcher, webhook listener) and push ``ScanEvent`` instances
    into the shared queue provided by the ``Watcher``.
    """

    @abc.abstractmethod
    async def start(self, queue: asyncio.Queue[ScanEvent]) -> None:
        """Begin producing events into *queue*.

        Called once when the watcher starts.  Implementations should spawn
        their own background tasks/loops and return promptly.
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop producing events and release resources.

        Called once during graceful shutdown.  Must be safe to call even
        if ``start`` was never called or already returned.
        """
